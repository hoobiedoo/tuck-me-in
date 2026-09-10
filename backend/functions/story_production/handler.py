"""Internal Tier 2 story-production orchestration.

Direct Lambda invocation only; this function is deliberately not exposed via
API Gateway. It composes the Stage 1 prompt input for manual use today and can
persist a reviewed Stage 1 response as draft catalogue rows. Bedrock invocation
is intentionally absent until model and review-boundary decisions are made.
"""

import base64
import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

import boto3
from botocore.config import Config

# In the deployed Lambda package (flat /var/task layout) house_style.py,
# prompt_compiler.py, and procedural_effects.py are already importable
# siblings. This directory only needs adding to sys.path explicitly when
# handler.py is loaded by file path from elsewhere (e.g. the test suite's
# importlib.util.spec_from_file_location), which doesn't otherwise put this
# directory on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from house_style import HOUSE_STYLE_VERSION, HOUSE_STYLES, compile_house_style_block, house_style_summary
from prompt_compiler import (
    PROMPT_COMPILER_VERSION,
    compile_background_prompt,
    compile_house_style_reference_prompt,
    compile_master_prompt,
    compile_static_prop_prompt,
    compile_variant_prompt,
)
import procedural_effects
from illustration_spec_schema import ILLUSTRATION_SPEC_SCHEMA, ILLUSTRATION_SPEC_TOOL_NAME
from story_spec_schema import STORY_SPEC_SCHEMA, STORY_SPEC_TOOL_NAME
from interactive_story_schema import INTERACTIVE_STORY_SCHEMA, INTERACTIVE_STORY_TOOL_NAME

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
# botocore's default read_timeout is 60s per attempt -- far too short for a
# non-streaming converse() call, which returns nothing until the *entire*
# generation finishes. A large Stage 2 output can take several minutes to
# generate, well past that default, regardless of the Lambda's own timeout
# (a different clock entirely). max_attempts=1: with a read_timeout this
# long, an automatic retry on a call that's still legitimately in progress
# would just double the wait rather than recover anything.
BEDROCK_TIMEOUT_CONFIG = Config(connect_timeout=60, read_timeout=850, retries={"max_attempts": 1})
bedrock_runtime = boto3.client("bedrock-runtime", config=BEDROCK_TIMEOUT_CONFIG)
# Separate client for the short Stability image calls (style guide, remove
# background, house-style reference): these are seconds long, not minutes,
# so real retries are safe here (unlike the long text calls above) and are
# what actually absorbs Bedrock's "Too many connections" throttling under
# the asset fan-out -- confirmed live: batching the fan-out alone (see
# ASSET_JOB_BATCH_SIZE) wasn't enough on its own.
BEDROCK_IMAGE_CONFIG = Config(connect_timeout=60, read_timeout=60, retries={"max_attempts": 5, "mode": "adaptive"})
bedrock_runtime_images = boto3.client("bedrock-runtime", config=BEDROCK_IMAGE_CONFIG)
bedrock_runtime_house_style_images = boto3.client(
    "bedrock-runtime", region_name=os.environ.get("BEDROCK_HOUSE_STYLE_REGION", "us-west-2"),
    config=BEDROCK_IMAGE_CONFIG,
)
lambda_client = boto3.client("lambda")
s3_client = boto3.client("s3")
CATALOGUE_ASSETS_BUCKET = os.environ.get("CATALOGUE_ASSETS_BUCKET")
CDN_DOMAIN = os.environ.get("CDN_DOMAIN", "")
SELF_FUNCTION_NAME = os.environ.get("STORY_PRODUCTION_SELF_FUNCTION_NAME")
theme_packs_table = dynamodb.Table(os.environ["THEME_PACKS_TABLE"])
assets_table = dynamodb.Table(os.environ["ASSETS_TABLE"])
story_templates_table = dynamodb.Table(os.environ["STORY_TEMPLATES_TABLE"])
story_template_pages_table = dynamodb.Table(os.environ["STORY_TEMPLATE_PAGES_TABLE"])
preset_cast_members_table = dynamodb.Table(os.environ["PRESET_CAST_MEMBERS_TABLE"])
developmental_frameworks_table = dynamodb.Table(os.environ["DEVELOPMENTAL_FRAMEWORKS_TABLE"])
jobs_table = dynamodb.Table(os.environ["STORY_PRODUCTION_JOBS_TABLE"]) if os.environ.get("STORY_PRODUCTION_JOBS_TABLE") else None

MIN_PAGE_COUNT = 10
LANGUAGE_CODE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
VALID_SLOT_TYPES = {"CONTROLLED_VOCAB", "CONTROLLED_VOCAB_WITH_OVERRIDE"}
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6"
)
STAGE_0_PROMPT_VERSION = "stage0-concept-studio-v1"
STAGE_0_PROMPT_PATH = (
    Path(__file__).resolve().parent / "prompts" / f"{STAGE_0_PROMPT_VERSION}.txt"
)
STAGE_1_PROMPT_VERSION = "stage1-story-slots-v1"
STAGE_1_PROMPT_PATH = (
    Path(__file__).resolve().parent / "prompts" / f"{STAGE_1_PROMPT_VERSION}.txt"
)
# New interactive content model (see docs/interactive-story-content-model.md)
# -- additive, parallel to the flat-slot Stage 1 above. Only reachable via
# compose_interactive_story/generate_interactive_story; generate_story and
# everything downstream of it (write_draft, Stage 2, story_instances) are
# untouched until this is validated and the rest of the pipeline is ready
# to consume entityChoices/branchPoints.
STAGE_1_INTERACTIVE_PROMPT_VERSION = "stage1-interactive-story-v1"
STAGE_1_INTERACTIVE_PROMPT_PATH = (
    Path(__file__).resolve().parent / "prompts" / f"{STAGE_1_INTERACTIVE_PROMPT_VERSION}.txt"
)
STAGE_2_PROMPT_VERSION = "stage2-illustration-spec-v2"
STAGE_2_PROMPT_PATH = (
    Path(__file__).resolve().parent / "prompts" / f"{STAGE_2_PROMPT_VERSION}.txt"
)
HOUSE_STYLE_MODEL_ID = os.environ.get("BEDROCK_HOUSE_STYLE_MODEL_ID", "stability.stable-image-core-v1:1")
STYLE_GUIDE_MODEL_ID = os.environ.get("BEDROCK_STYLE_GUIDE_MODEL_ARN")
REMOVE_BG_MODEL_ID = os.environ.get("BEDROCK_REMOVE_BG_MODEL_ARN")
BACKGROUND_LAYER_TYPE = "background"

# Style Guide `fidelity`: how strongly it follows the reference image's own
# content vs. just its rendering style. Confirmed live: default/high fidelity
# reproduces the reference's whole scene (unusable for isolating a subject);
# ~0.2-0.3 keeps only palette/line-style cues.
MASTER_FIDELITY = 0.3   # new identity: needs room to actually invent a new character
VARIANT_FIDELITY = 0.2  # existing identity: needs near-total preservation
STATIC_PROP_FIDELITY = 0.2

ASSET_KINDS = {
    "NEW_IDENTITY", "VARIANT_OF_IDENTITY", "BACKGROUND",
    "PROCEDURAL_EFFECT", "STATIC_PROP",
}

# Fanning out every asset's Lambda invocation in one tight loop puts that many
# simultaneous InvokeModel calls on Bedrock's style-guide model at once --
# confirmed live: a ~20-asset story threw "Too many connections" on most of
# them. Firing invocations in small batches, with a pause between batches,
# keeps concurrent Bedrock calls within what the account can actually serve.
ASSET_JOB_BATCH_SIZE = 4
ASSET_JOB_BATCH_DELAY_SECONDS = 3


class InputError(ValueError):
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def lambda_handler(event, context):
    """Handle one stateless production action.

    Actions:
      prepare     Return producer questions, cast choices, and existing premises.
      compose_concepts Return the Concept Studio input for manual AI use.
      generate_concepts Generate and validate concepts with Amazon Bedrock.
      compose     Return the exact Stage 1 input object for manual prompt use.
      generate_story Generate and validate a complete story with Amazon Bedrock.
      compose_interactive_story Return the interactive-content-model Stage 1
                  input and assembled prompt for manual prompt use, no model
                  call. See docs/interactive-story-content-model.md.
      generate_interactive_story Generate and validate a story using the new
                  entityChoices/entityReferences/branchPoints content model.
                  Additive/experimental -- not yet consumed by Stage 2 or
                  story_instances.
      write_draft Validate reviewed Stage 1 JSON and write draft catalogue rows.
      write_interactive_draft write_draft's counterpart for the interactive
                  content model -- writes entityChoices/branchPoints and
                  every spine/branch page as draft catalogue rows.
      generate_illustration_spec Generate and validate an illustration spec
                  (Stage 2) for a Stage 1 story with Amazon Bedrock.
      compose_illustration_spec Return the exact Stage 2 input and assembled
                  prompt for manual prompt use, no model call.
      generate_illustrations Fan out one async image-generation job per reviewed
                  illustration spec (Stage 2 output).
      generate_asset_image Internal worker job: render one asset image and
                  upload it to the catalogue assets bucket.
    """
    if (event or {}).get("_jobId"):
        return _run_job(event)
    try:
        return _dispatch(event or {})
    except InputError as error:
        return {"status": "refused", "field": error.field, "reason": str(error)}


def _dispatch(event):
        action = event.get("action")
        logger.info("dispatch action=%s", action)
        if action == "prepare":
            return _prepare(event)
        if action == "compose_concepts":
            return _compose_concepts(event)
        if action == "generate_concepts":
            return _generate_concepts(event)
        if action == "compose":
            return _compose(event)
        if action == "generate_story":
            return _generate_story(event)
        if action == "compose_interactive_story":
            return _compose_interactive_story_action(event)
        if action == "generate_interactive_story":
            return _generate_interactive_story(event)
        if action == "write_draft":
            return _write_draft(event)
        if action == "write_interactive_draft":
            return _write_interactive_draft(event)
        if action == "generate_illustration_spec":
            return _generate_illustration_spec(event)
        if action == "compose_illustration_spec":
            return _compose_illustration_spec_action(event)
        if action == "generate_illustrations":
            return _generate_illustrations(event)
        if action == "generate_asset_image":
            return _generate_asset_image(event)
        raise InputError(
            "action",
            "action must be 'prepare', 'compose_concepts', 'generate_concepts', "
            "'compose', 'generate_story', 'compose_interactive_story', "
            "'generate_interactive_story', 'write_draft', 'write_interactive_draft', "
            "'generate_illustration_spec', 'compose_illustration_spec', "
            "'generate_illustrations', or 'generate_asset_image'.",
        )


def _run_job(event):
    job_id = event.pop("_jobId")
    started = time.monotonic()
    logger.info("job start jobId=%s action=%s", job_id, event.get("action"))
    try:
        result = _dispatch(event)
        jobs_table.update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET #s = :s, #r = :r",
            ExpressionAttributeNames={"#s": "status", "#r": "result"},
            ExpressionAttributeValues={":s": "completed", ":r": _dynamo_safe(result)},
        )
        logger.info("job completed jobId=%s elapsedSec=%.1f", job_id, time.monotonic() - started)
    except Exception as error:
        logger.exception("job failed jobId=%s elapsedSec=%.1f", job_id, time.monotonic() - started)
        jobs_table.update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET #s = :s, errorMessage = :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "failed", ":e": str(error)},
        )
        # Not re-raised: the failure is already fully recorded above (job
        # row + full traceback via logger.exception) -- from here this
        # invocation is done, not erroring. Re-raising would tell Lambda the
        # invocation itself failed, triggering its automatic async-retry
        # policy (up to 2 more attempts) on a job that's already terminal,
        # silently burning real Bedrock cost and cluttering logs with
        # attempts the app has long since stopped polling for.
        return None
    return result


def _prepare(event):
    pack, framework, language_code = _load_context(event)
    premises = _existing_premises(pack["themePackId"], framework["frameworkId"], language_code)
    return {
        "status": "ok",
        "action": "prepare",
        "themePack": {
            "themePackId": pack["themePackId"],
            "name": pack["name"],
            "tone": pack.get("description", ""),
            "catalogueStatus": pack.get("catalogueStatus", "draft"),
        },
        "framework": {
            "frameworkId": framework["frameworkId"],
            "displayName": framework.get("displayName", framework["frameworkId"]),
            "narrativeGuidance": framework.get("narrativeGuidance", ""),
            "creativeBriefQuestions": framework.get("creativeBriefQuestions", []),
            "catalogueStatus": framework.get("catalogueStatus", "draft"),
        },
        "languageCode": language_code,
        "castMembers": _cast_members(pack["themePackId"]),
        "existingStoryPremises": premises,
    }


def _compose(event):
    pack, framework, language_code = _load_context(event)
    cast_member_id = _required_string(event, "castMemberId")
    cast_member = preset_cast_members_table.get_item(
        Key={"castMemberId": cast_member_id}
    ).get("Item")
    if not cast_member:
        raise InputError("castMemberId", "The selected cast member does not exist.")
    if (cast_member.get("availableThemePacks")
            and pack["themePackId"] not in cast_member["availableThemePacks"]):
        raise InputError("castMemberId", "The selected cast member is not available for this theme pack.")

    minimum = event.get("minPageCount", MIN_PAGE_COUNT)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < MIN_PAGE_COUNT:
        raise InputError("minPageCount", f"minPageCount must be an integer of at least {MIN_PAGE_COUNT}.")

    selected_concept_brief = _selected_concept_brief(event)
    creative_brief = selected_concept_brief or _creative_brief(event, framework)
    premises = _existing_premises(pack["themePackId"], framework["frameworkId"], language_code)
    stage1_input = {
        "THEME_PACK_NAME": pack["name"],
        "THEME_PACK_TONE": pack.get("description", ""),
        "DEVELOPMENTAL_FRAMEWORK": framework["frameworkId"],
        "FRAMEWORK_NARRATIVE_GUIDANCE": framework.get("narrativeGuidance", ""),
        "LANGUAGE_CODE": language_code,
        "CAST_NAME": cast_member["name"],
        "CAST_DESCRIPTION": cast_member.get("personalityDescription", ""),
        "MIN_PAGE_COUNT": minimum,
        "EXISTING_SLOT_VOCABULARY": _slot_vocabulary(pack["themePackId"]),
        "EXISTING_NAME_SUGGESTIONS": _name_suggestions(pack, language_code),
        "CREATIVE_BRIEF": creative_brief,
        "EXISTING_STORY_PREMISES": premises,
    }
    working_title = event.get("workingTitle")
    if not working_title and selected_concept_brief:
        working_title = event["selectedConcept"]["workingTitle"]
    if working_title:
        if not isinstance(working_title, str):
            raise InputError("workingTitle", "workingTitle must be a string when supplied.")
        stage1_input["WORKING_TITLE"] = working_title.strip()

    return {
        "status": "ok",
        "action": "compose",
        "mode": "manual",
        "promptVersion": STAGE_1_PROMPT_VERSION,
        "stage1Input": stage1_input,
        "assembledPrompt": _assemble_prompt(
            STAGE_1_PROMPT_PATH, "STAGE_1_INPUT_JSON", stage1_input,
            tool_name=STORY_SPEC_TOOL_NAME, tool_schema=STORY_SPEC_SCHEMA,
        ),
        "writeContext": {
            "themePackId": pack["themePackId"],
            "frameworkId": framework["frameworkId"],
            "languageCode": language_code,
            "castMemberId": cast_member_id,
            "minPageCount": minimum,
            **({"translationGroupId": event["translationGroupId"]} if event.get("translationGroupId") else {}),
        },
    }


def _compose_concepts(event):
    """Compose a divergent concept-design input; no model call occurs here."""
    pack, framework, language_code = _load_context(event)
    cast_member_id = _required_string(event, "castMemberId")
    cast_member = preset_cast_members_table.get_item(
        Key={"castMemberId": cast_member_id}
    ).get("Item")
    if not cast_member:
        raise InputError("castMemberId", "The selected cast member does not exist.")
    if (cast_member.get("availableThemePacks")
            and pack["themePackId"] not in cast_member["availableThemePacks"]):
        raise InputError("castMemberId", "The selected cast member is not available for this theme pack.")

    family_intent = _required_string(event, "familyIntent")
    concept_count = event.get("conceptCount", 3)
    if isinstance(concept_count, bool) or not isinstance(concept_count, int) or not 3 <= concept_count <= 5:
        raise InputError("conceptCount", "conceptCount must be an integer from 3 through 5.")

    concept_input = {
        "THEME_PACK_NAME": pack["name"],
        "THEME_PACK_TONE": pack.get("description", ""),
        "DEVELOPMENTAL_FRAMEWORK": framework["frameworkId"],
        "FRAMEWORK_NARRATIVE_GUIDANCE": framework.get("narrativeGuidance", ""),
        "LANGUAGE_CODE": language_code,
        "CAST_NAME": cast_member["name"],
        "CAST_DESCRIPTION": cast_member.get("personalityDescription", ""),
        "FAMILY_INTENT": family_intent,
        "PRODUCER_ANSWERS": _brief_answers(event, framework),
        "EXISTING_SLOT_VOCABULARY": _slot_vocabulary(pack["themePackId"]),
        "EXISTING_STORY_PREMISES": _existing_premises(
            pack["themePackId"], framework["frameworkId"], language_code
        ),
        "CONCEPT_COUNT": concept_count,
    }
    assembled_prompt = _assemble_prompt(
        STAGE_0_PROMPT_PATH, "CONCEPT_INPUT_JSON", concept_input
    )
    return {
        "status": "ok",
        "action": "compose_concepts",
        "mode": "manual",
        "promptVersion": STAGE_0_PROMPT_VERSION,
        "conceptInput": concept_input,
        "assembledPrompt": assembled_prompt,
        "selectionContext": {
            "themePackId": pack["themePackId"],
            "frameworkId": framework["frameworkId"],
            "languageCode": language_code,
            "castMemberId": cast_member_id,
        },
    }


def _generate_concepts(event):
    composed = _compose_concepts(event)
    output = _invoke_bedrock_json(
        STAGE_0_PROMPT_PATH,
        "CONCEPT_INPUT_JSON",
        composed["conceptInput"],
        max_tokens=6000,
    )
    concepts = _validate_concepts(output, composed["conceptInput"]["CONCEPT_COUNT"])
    return {
        "status": "ok",
        "action": "generate_concepts",
        "mode": "bedrock",
        "modelId": BEDROCK_MODEL_ID,
        "promptVersion": STAGE_0_PROMPT_VERSION,
        "concepts": concepts,
        "selectionContext": composed["selectionContext"],
    }


def _generate_story(event):
    composed = _compose(event)
    output = _invoke_bedrock_tool(
        STAGE_1_PROMPT_PATH,
        "STAGE_1_INPUT_JSON",
        composed["stage1Input"],
        max_tokens=16000,
        tool_name=STORY_SPEC_TOOL_NAME,
        tool_schema=STORY_SPEC_SCHEMA,
    )
    if output.get("status") == "refused":
        return {
            **output,
            "action": "generate_story",
            "mode": "bedrock",
            "modelId": BEDROCK_MODEL_ID,
            "promptVersion": STAGE_1_PROMPT_VERSION,
        }
    if output.get("status") != "ok":
        raise InputError("modelOutput.status", "Bedrock output status must be 'ok' or 'refused'.")
    _validate_output(
        output.get("storyTemplate"),
        output.get("pages"),
        composed["writeContext"]["frameworkId"],
        composed["writeContext"]["languageCode"],
        composed["writeContext"]["minPageCount"],
        output.get("newSlotTagsNeedingArt"),
    )
    return {
        "status": "ok",
        "action": "generate_story",
        "mode": "bedrock",
        "modelId": BEDROCK_MODEL_ID,
        "promptVersion": STAGE_1_PROMPT_VERSION,
        "stage1Output": output,
        "writeContext": composed["writeContext"],
    }


def _compose_interactive_story_action(event):
    composed = _compose(event)
    return {
        "status": "ok",
        "action": "compose_interactive_story",
        "mode": "manual",
        "promptVersion": STAGE_1_INTERACTIVE_PROMPT_VERSION,
        "stage1Input": composed["stage1Input"],
        "assembledPrompt": _assemble_prompt(
            STAGE_1_INTERACTIVE_PROMPT_PATH, "STAGE_1_INPUT_JSON", composed["stage1Input"],
            tool_name=INTERACTIVE_STORY_TOOL_NAME, tool_schema=INTERACTIVE_STORY_SCHEMA,
        ),
        "writeContext": composed["writeContext"],
    }


def _generate_interactive_story(event):
    """New interactive content model (docs/interactive-story-content-model.md):
    entityChoices + entityReferences + branchPoints in place of flat {{slot}}
    substitution. Additive and parallel to _generate_story -- nothing
    downstream (write_draft, Stage 2, story_instances) consumes this output
    yet; this exists to validate the shape and prompt in isolation first.
    """
    composed = _compose(event)
    output = _invoke_bedrock_tool(
        STAGE_1_INTERACTIVE_PROMPT_PATH, "STAGE_1_INPUT_JSON", composed["stage1Input"], max_tokens=16000,
        tool_name=INTERACTIVE_STORY_TOOL_NAME, tool_schema=INTERACTIVE_STORY_SCHEMA,
    )
    if output.get("status") == "refused":
        return {
            **output,
            "action": "generate_interactive_story",
            "mode": "bedrock",
            "modelId": BEDROCK_MODEL_ID,
            "promptVersion": STAGE_1_INTERACTIVE_PROMPT_VERSION,
        }
    if output.get("status") != "ok":
        raise InputError("modelOutput.status", "Bedrock output status must be 'ok' or 'refused'.")
    _validate_interactive_story_output(
        output,
        composed["writeContext"]["frameworkId"],
        composed["writeContext"]["languageCode"],
        composed["writeContext"]["minPageCount"],
    )
    return {
        "status": "ok",
        "action": "generate_interactive_story",
        "mode": "bedrock",
        "modelId": BEDROCK_MODEL_ID,
        "promptVersion": STAGE_1_INTERACTIVE_PROMPT_VERSION,
        "stage1Output": output,
        "writeContext": composed["writeContext"],
    }


def _validate_interactive_story_output(output, framework_id, language_code, minimum):
    template = output.get("storyTemplate")
    if not isinstance(template, dict):
        raise InputError("stage1Output.storyTemplate", "storyTemplate must be an object.")
    for field in ("title", "oneLineSummary"):
        if not isinstance(template.get(field), str) or not template[field].strip():
            raise InputError(f"stage1Output.storyTemplate.{field}", f"{field} must be a non-empty string.")
    if template.get("developmentalFramework") != framework_id:
        raise InputError("stage1Output.storyTemplate.developmentalFramework", "The output framework does not match frameworkId.")
    if template.get("languageCode") != language_code:
        raise InputError("stage1Output.storyTemplate.languageCode", "The output language does not match languageCode.")

    entity_choices = output.get("entityChoices")
    if not isinstance(entity_choices, list) or not entity_choices:
        raise InputError("stage1Output.entityChoices", "entityChoices must be a non-empty array.")
    choices_by_id = {}
    for index, choice in enumerate(entity_choices):
        choice_id = choice.get("choiceId") if isinstance(choice, dict) else None
        if not choice_id or choice_id in choices_by_id:
            raise InputError("stage1Output.entityChoices", f"entityChoices[{index}] must have a non-empty, unique choiceId.")
        options = choice.get("options")
        if not isinstance(options, list) or not (2 <= len(options) <= 4):
            raise InputError(f"stage1Output.entityChoices.{choice_id}", "options must have 2-4 entries.")
        option_ids = set()
        for opt_index, option in enumerate(options):
            option_id = option.get("optionId") if isinstance(option, dict) else None
            if not option_id or option_id in option_ids:
                raise InputError(f"stage1Output.entityChoices.{choice_id}.options", f"options[{opt_index}] must have a non-empty, unique optionId.")
            option_ids.add(option_id)
            for field in ("displayLabel", "revealLine"):
                value = option.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise InputError(f"stage1Output.entityChoices.{choice_id}.options.{option_id}", f"{field} is required.")
                if any(char in value for char in _DASH_CHARS):
                    raise InputError(f"stage1Output.entityChoices.{choice_id}.options.{option_id}.{field}", "must not contain an em dash (—) or en dash (–).")
        choices_by_id[choice_id] = option_ids

    presented = set()
    referenced = set()
    branch_driven = set()
    seen_page_orders = set()

    pages = output.get("pages")
    if not isinstance(pages, list) or not pages:
        raise InputError("stage1Output.pages", "pages must be a non-empty array.")
    for page in pages:
        order = page.get("pageOrder") if isinstance(page, dict) else None
        if not order or order in seen_page_orders:
            raise InputError("stage1Output.pages", f"Duplicate or missing pageOrder '{order}'.")
        seen_page_orders.add(order)
        _validate_interactive_page(page, choices_by_id, presented, referenced)

    branch_points = output.get("branchPoints") or []
    if not isinstance(branch_points, list):
        raise InputError("stage1Output.branchPoints", "branchPoints must be an array.")
    total_branch_pages = 0
    for bp_index, branch_point in enumerate(branch_points):
        choice_id = branch_point.get("choiceId") if isinstance(branch_point, dict) else None
        option_ids = choices_by_id.get(choice_id)
        if option_ids is None:
            raise InputError("stage1Output.branchPoints", f"branchPoints[{bp_index}] references unknown choiceId '{choice_id}'.")
        branch_pages_by_option = branch_point.get("branchPages")
        if not isinstance(branch_pages_by_option, dict) or set(branch_pages_by_option.keys()) != option_ids:
            raise InputError(
                f"stage1Output.branchPoints.{choice_id}.branchPages",
                f"branchPages keys must exactly match this choice's optionIds: {sorted(option_ids)}.",
            )
        lengths = set()
        for option_id, branch_page_list in branch_pages_by_option.items():
            if not isinstance(branch_page_list, list) or not (1 <= len(branch_page_list) <= 3):
                raise InputError(f"stage1Output.branchPoints.{choice_id}.branchPages.{option_id}", "must be an array of 1-3 pages.")
            lengths.add(len(branch_page_list))
            for page in branch_page_list:
                order = page.get("pageOrder") if isinstance(page, dict) else None
                if not order or order in seen_page_orders:
                    raise InputError(f"stage1Output.branchPoints.{choice_id}.branchPages.{option_id}", f"Duplicate or missing pageOrder '{order}'.")
                seen_page_orders.add(order)
                _validate_interactive_page(page, choices_by_id, presented, referenced)
        if len(lengths) != 1:
            raise InputError(
                f"stage1Output.branchPoints.{choice_id}.branchPages",
                "Every branch must have the exact same number of pages -- the reconvergence guarantee.",
            )
        total_branch_pages += lengths.pop()
        presented.add(choice_id)  # the branch point itself is how this choice gets presented
        branch_driven.add(choice_id)  # its payoff IS the differing branch content -- no separate callback needed
        if branch_point.get("afterPageOrder") not in seen_page_orders:
            raise InputError(f"stage1Output.branchPoints.{choice_id}", f"afterPageOrder '{branch_point.get('afterPageOrder')}' does not match any spine page.")
        if branch_point.get("reconvergesAtPageOrder") not in seen_page_orders:
            raise InputError(f"stage1Output.branchPoints.{choice_id}", f"reconvergesAtPageOrder '{branch_point.get('reconvergesAtPageOrder')}' does not match any spine page.")

    for choice_id in choices_by_id:
        if choice_id not in presented:
            raise InputError("stage1Output.entityChoices", f"entityChoice '{choice_id}' is never presented (no presentsChoice page and no branchPoint).")
        if choice_id not in referenced and choice_id not in branch_driven:
            raise InputError("stage1Output.entityChoices", f"entityChoice '{choice_id}' is introduced but never referenced again later in the story -- the callback is the point.")

    total_pages = len(pages) + total_branch_pages
    if total_pages < minimum:
        raise InputError("stage1Output.pages", f"At least {minimum} pages are required along any single resolved reading (found {total_pages}).")


def _validate_interactive_page(page, choices_by_id, presented, referenced):
    if not isinstance(page, dict):
        raise InputError("stage1Output.pages", "Every page must be an object.")
    order = page.get("pageOrder", "?")
    text = page.get("textTemplate")
    if not isinstance(text, str) or not text.strip():
        raise InputError(f"stage1Output.pages[{order}].textTemplate", "textTemplate must be non-empty.")
    if any(char in text for char in _DASH_CHARS):
        raise InputError(f"stage1Output.pages[{order}].textTemplate", "textTemplate must not contain an em dash (—) or en dash (–).")
    if not isinstance(page.get("sceneDescription"), str) or not page["sceneDescription"].strip():
        raise InputError(f"stage1Output.pages[{order}].sceneDescription", "sceneDescription must be non-empty.")

    presents = page.get("presentsChoice")
    if presents is not None:
        if presents not in choices_by_id:
            raise InputError(f"stage1Output.pages[{order}].presentsChoice", f"Unknown choiceId '{presents}'.")
        if presents in presented:
            raise InputError(f"stage1Output.pages[{order}].presentsChoice", f"entityChoice '{presents}' is presented more than once.")
        presented.add(presents)

    for ref_index, ref in enumerate(page.get("entityReferences") or []):
        choice_id = ref.get("choiceId") if isinstance(ref, dict) else None
        option_ids = choices_by_id.get(choice_id)
        if option_ids is None:
            raise InputError(f"stage1Output.pages[{order}].entityReferences[{ref_index}]", f"Unknown choiceId '{choice_id}'.")
        text_by_option = ref.get("textByOption")
        if not isinstance(text_by_option, dict) or set(text_by_option.keys()) != option_ids:
            raise InputError(
                f"stage1Output.pages[{order}].entityReferences[{ref_index}]",
                f"textByOption keys must exactly match choiceId '{choice_id}''s optionIds: {sorted(option_ids)}.",
            )
        for option_id, sentence in text_by_option.items():
            if not isinstance(sentence, str) or not sentence.strip():
                raise InputError(f"stage1Output.pages[{order}].entityReferences[{ref_index}].{option_id}", "Callback sentence must be non-empty.")
            if any(char in sentence for char in _DASH_CHARS):
                raise InputError(f"stage1Output.pages[{order}].entityReferences[{ref_index}].{option_id}", "must not contain an em dash (—) or en dash (–).")
        referenced.add(choice_id)

    # Free-text slots (e.g. a name) reuse the old, simpler mechanism.
    slots = page.get("slots") or []
    slot_ids = set()
    for slot in slots:
        slot_id = slot.get("slotId") if isinstance(slot, dict) else None
        if not slot_id or slot_id in slot_ids:
            raise InputError(f"stage1Output.pages[{order}].slots", "Every slotId must be non-empty and unique on its page.")
        slot_ids.add(slot_id)
        slot_tag = slot.get("slotTag")
        if not slot_tag:
            raise InputError(f"stage1Output.pages[{order}].slots.{slot_id}", "slotTag is required.")
        if not _slot_id_pattern(slot_tag).match(slot_id):
            raise InputError(f"stage1Output.pages[{order}].slots.{slot_id}", f"slotId '{slot_id}' must be '{slot_tag}_slot'.")
        if f"{{{{{slot_id}}}}}" not in text:
            raise InputError(f"stage1Output.pages[{order}].textTemplate", f"Missing placeholder for slotId '{slot_id}'.")
    defaults = page.get("defaultValuesBySlot") or {}
    if not isinstance(defaults, dict) or any(key not in slot_ids for key in defaults):
        raise InputError(f"stage1Output.pages[{order}].defaultValuesBySlot", "Defaults may only reference slots declared on the page.")


def _assemble_prompt(prompt_path, input_label, prompt_input, tool_name=None, tool_schema=None):
    try:
        instructions = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"Runtime prompt could not be loaded: {prompt_path.name}") from error
    text = (
        f"{instructions}\n\n"
        f"{input_label}\n"
        f"{json.dumps(prompt_input, ensure_ascii=False, indent=2)}"
    )
    if tool_schema:
        # The live call constrains the response via Bedrock tool use, which
        # a plain chat UI has no equivalent for -- append the schema so a
        # manual tester can ask the model to conform to it directly instead.
        text += (
            f"\n\n(When run through this pipeline, the model must call a tool named "
            f"'{tool_name}' whose input matches this JSON Schema. Testing by hand in a "
            f"plain chat UI: ask for ONLY a JSON object matching this schema, no other text.)\n"
            f"{json.dumps(tool_schema, ensure_ascii=False, indent=2)}"
        )
    return text


def _extract_json_object(text):
    """Parse the JSON object out of a Bedrock text response, tolerating
    reasoning prose or reviewer notes the model wrote before/after it despite
    being told not to (confirmed live: a "pre-flight analysis" essay before
    the JSON and "post-output notes" after it, for a long judgment-heavy
    Stage 2 input) -- a plain json.loads on the whole response breaks the
    moment there's anything surrounding the JSON itself.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for match in re.finditer(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL):
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue

    # No fenced block either -- scan for the first balanced top-level {...}.
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)

    raise json.JSONDecodeError("No parseable JSON object found in response", text, 0)


def _invoke_bedrock_json(prompt_path, input_label, prompt_input, max_tokens, trailing_reminder=None):
    try:
        instructions = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"Runtime prompt could not be loaded: {prompt_path.name}") from error
    input_json = json.dumps(prompt_input, ensure_ascii=False)
    user_text = f"{input_label}\n{input_json}"
    if trailing_reminder:
        # The instruction against pre/post-JSON prose already lives in the
        # system prompt, but for a long, judgment-heavy input the model can
        # still "think out loud" before/after the JSON despite it. Repeating
        # it as the very last thing the model reads before generating (after
        # the input, not just once early in a long system prompt) measurably
        # reduces that -- confirmed after a real 88s/7190-token response that
        # was mostly a discarded reasoning essay wrapped around the JSON.
        user_text += f"\n\n{trailing_reminder}"
    logger.info(
        "bedrock converse start prompt=%s model=%s maxTokens=%d inputChars=%d",
        prompt_path.name, BEDROCK_MODEL_ID, max_tokens, len(input_json),
    )
    started = time.monotonic()
    response = bedrock_runtime.converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": instructions}],
        messages=[{
            "role": "user",
            "content": [{"text": user_text}],
        }],
        inferenceConfig={
            "maxTokens": max_tokens,
            "temperature": 0.7,
        },
    )
    elapsed = time.monotonic() - started
    usage = response.get("usage", {})
    logger.info(
        "bedrock converse done prompt=%s elapsedSec=%.1f stopReason=%s outputTokens=%s",
        prompt_path.name, elapsed, response.get("stopReason"), usage.get("outputTokens"),
    )
    if response.get("stopReason") == "max_tokens":
        # Distinguish from a genuinely malformed response below: this is
        # Bedrock cutting the JSON off mid-structure because it hit
        # maxTokens, not the model producing invalid output.
        raise InputError(
            "modelOutput",
            f"Bedrock output was truncated at the {max_tokens}-token limit before finishing; "
            "raise max_tokens for this call.",
        )
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict)).strip()
    try:
        result = _extract_json_object(text)
    except json.JSONDecodeError as error:
        # The generic "invalid JSON" message alone gives nothing to act on --
        # log the actual text so the next failure shows exactly what broke
        # (stray prose, a formatting slip, silent truncation not caught by
        # the stopReason check above, etc.) instead of just that it happened.
        logger.error(
            "bedrock returned invalid JSON, prompt=%s textChars=%d error=%s\n--- first 3000 chars ---\n%s\n--- last 3000 chars ---\n%s",
            prompt_path.name, len(text), error, text[:3000], text[-3000:],
        )
        raise InputError("modelOutput", "Bedrock returned invalid JSON.") from error
    if not isinstance(result, dict):
        raise InputError("modelOutput", "Bedrock output must be a JSON object.")
    return result


def _invoke_bedrock_tool(prompt_path, input_label, prompt_input, max_tokens, tool_name, tool_schema):
    """Like _invoke_bedrock_json, but constrains the response to a JSON
    Schema via tool use instead of asking for JSON in prose and parsing free
    text on the way back.

    Two failure modes _invoke_bedrock_json can only catch after the fact
    (wrong type for a numeric field, an enum value outside a fixed list)
    become something the model can't produce in the first place, and the
    "reasoning essay wrapped around the JSON" parsing problem _extract_json_
    object works around doesn't exist here -- the response is a structured
    tool-call argument, not text to extract a JSON object out of.
    """
    try:
        instructions = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"Runtime prompt could not be loaded: {prompt_path.name}") from error
    input_json = json.dumps(prompt_input, ensure_ascii=False)
    user_text = f"{input_label}\n{input_json}"
    logger.info(
        "bedrock converse (tool) start prompt=%s model=%s tool=%s maxTokens=%d inputChars=%d",
        prompt_path.name, BEDROCK_MODEL_ID, tool_name, max_tokens, len(input_json),
    )
    started = time.monotonic()
    response = bedrock_runtime.converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": instructions}],
        messages=[{
            "role": "user",
            "content": [{"text": user_text}],
        }],
        inferenceConfig={
            "maxTokens": max_tokens,
            "temperature": 0.7,
        },
        toolConfig={
            "tools": [{
                "toolSpec": {
                    "name": tool_name,
                    "inputSchema": {"json": tool_schema},
                }
            }],
            "toolChoice": {"tool": {"name": tool_name}},
        },
    )
    elapsed = time.monotonic() - started
    usage = response.get("usage", {})
    logger.info(
        "bedrock converse (tool) done prompt=%s elapsedSec=%.1f stopReason=%s outputTokens=%s",
        prompt_path.name, elapsed, response.get("stopReason"), usage.get("outputTokens"),
    )
    if response.get("stopReason") == "max_tokens":
        raise InputError(
            "modelOutput",
            f"Bedrock output was truncated at the {max_tokens}-token limit before finishing; "
            "raise max_tokens for this call.",
        )
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    for block in blocks:
        if isinstance(block, dict) and "toolUse" in block:
            result = block["toolUse"].get("input")
            if not isinstance(result, dict):
                raise InputError("modelOutput", "Bedrock tool call returned no usable input object.")
            return result
    raise InputError("modelOutput", f"Bedrock did not call the '{tool_name}' tool (stopReason={response.get('stopReason')}).")


def _validate_concepts(output, expected_count):
    if output.get("status") == "refused":
        raise InputError("modelOutput", output.get("reason", "Bedrock refused the concept request."))
    concepts = output.get("concepts")
    if output.get("status") != "ok" or not isinstance(concepts, list):
        raise InputError("modelOutput", "Bedrock output must contain status 'ok' and a concepts array.")
    if len(concepts) != expected_count:
        raise InputError("modelOutput.concepts", f"Bedrock must return exactly {expected_count} concepts.")
    required_strings = (
        "workingTitle", "toddlerHook", "emotionalPromise", "centralSituation",
        "resolution", "repeatableElement", "familyConnection", "bedtimeEnding",
        "distinctnessRationale",
    )
    required_lists = (
        "personalizationMoments", "existingSlotTagsToReuse",
        "newArtLikelyNeeded", "risks",
    )
    for index, concept in enumerate(concepts):
        if not isinstance(concept, dict):
            raise InputError("modelOutput.concepts", f"Concept {index + 1} must be an object.")
        for field in required_strings:
            if not isinstance(concept.get(field), str) or not concept[field].strip():
                raise InputError("modelOutput.concepts", f"Concept {index + 1}.{field} is required.")
        for field in required_lists:
            if not isinstance(concept.get(field), list) or not all(
                isinstance(value, str) for value in concept[field]
            ):
                raise InputError("modelOutput.concepts", f"Concept {index + 1}.{field} must be a string array.")
    return concepts


def _write_draft(event):
    pack, framework, language_code = _load_context(event)
    cast_member_id = _required_string(event, "castMemberId")
    cast_member = preset_cast_members_table.get_item(
        Key={"castMemberId": cast_member_id}
    ).get("Item")
    if not cast_member:
        raise InputError("castMemberId", "The selected cast member does not exist.")
    if (cast_member.get("availableThemePacks")
            and pack["themePackId"] not in cast_member["availableThemePacks"]):
        raise InputError("castMemberId", "The selected cast member is not available for this theme pack.")
    output = event.get("stage1Output")
    if not isinstance(output, dict):
        raise InputError("stage1Output", "stage1Output must be the reviewed Stage 1 JSON object.")
    if output.get("status") == "refused":
        raise InputError("stage1Output", "A refused Stage 1 response cannot be written.")
    if output.get("status") != "ok":
        raise InputError("stage1Output.status", "stage1Output.status must be 'ok'.")

    minimum = event.get("minPageCount", MIN_PAGE_COUNT)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < MIN_PAGE_COUNT:
        raise InputError("minPageCount", f"minPageCount must be an integer of at least {MIN_PAGE_COUNT}.")

    template = output.get("storyTemplate")
    pages = output.get("pages")
    _validate_output(
        template, pages, framework["frameworkId"], language_code, minimum,
        output.get("newSlotTagsNeedingArt"),
    )

    story_template_id = str(uuid.uuid4())
    translation_group_id = event.get("translationGroupId") or str(uuid.uuid4())
    unresolved = output.get("newSlotTagsNeedingArt") or []
    template_item = {
        "storyTemplateId": story_template_id,
        "translationGroupId": translation_group_id,
        "themePackId": pack["themePackId"],
        "castMemberId": cast_member_id,
        "developmentalFramework": framework["frameworkId"],
        "languageCode": language_code,
        "title": template["title"].strip(),
        "oneLineSummary": template["oneLineSummary"].strip(),
        "isQuickStoryDefault": False,
        "catalogueStatus": "draft",
    }
    if unresolved:
        template_item["unresolvedSlotTags"] = unresolved
    if output.get("newNameSuggestionsProposed"):
        template_item["proposedNameSuggestions"] = output["newNameSuggestionsProposed"]

    resolved_pages = [
        _page_item(story_template_id, pack["themePackId"], language_code, page)
        for page in pages
    ]

    # Validate and resolve every page before the first write. Draft status
    # keeps partially illustrated content out of all consumer paths.
    story_templates_table.put_item(Item=template_item)
    with story_template_pages_table.batch_writer() as batch:
        for page in resolved_pages:
            batch.put_item(Item=page)

    return {
        "status": "ok",
        "action": "write_draft",
        "storyTemplateId": story_template_id,
        "translationGroupId": translation_group_id,
        "pageCount": len(resolved_pages),
        "catalogueStatus": "draft",
        "unresolvedSlotTags": unresolved,
    }


def _write_interactive_draft(event):
    """write_draft's counterpart for the interactive content model (see
    docs/interactive-story-content-model.md). Separate from _write_draft
    rather than unified with it -- the old function is tightly coupled to
    the flat {{slot}} shape via _validate_output/_page_item, and this way
    nothing about the currently-working path is at risk.

    Spine pages and every branchPoint's branch pages all become individual
    rows in story_template_pages_table (same table, same key shape:
    storyTemplateId + pageOrder) -- a branch page's disambiguated pageOrder
    ("0004a") sorts correctly between its neighbors with no special-casing.
    entityChoices and branchPoint metadata (which pageOrders belong to which
    option -- not the page content itself, that's already in the page rows)
    live on the template item, since they're small and bounded.

    Tags the template with contentModel: "INTERACTIVE_V1" so any reader of
    story_templates_table (story_preview, story_instances, future code) can
    tell the two shapes apart once both exist in the same table -- cheap
    insurance against silently misinterpreting one as the other later.
    """
    pack, framework, language_code = _load_context(event)
    cast_member_id = _required_string(event, "castMemberId")
    cast_member = preset_cast_members_table.get_item(
        Key={"castMemberId": cast_member_id}
    ).get("Item")
    if not cast_member:
        raise InputError("castMemberId", "The selected cast member does not exist.")
    if (cast_member.get("availableThemePacks")
            and pack["themePackId"] not in cast_member["availableThemePacks"]):
        raise InputError("castMemberId", "The selected cast member is not available for this theme pack.")

    output = event.get("stage1Output")
    if not isinstance(output, dict):
        raise InputError("stage1Output", "stage1Output must be the reviewed interactive Stage 1 JSON object.")
    if output.get("status") == "refused":
        raise InputError("stage1Output", "A refused Stage 1 response cannot be written.")
    if output.get("status") != "ok":
        raise InputError("stage1Output.status", "stage1Output.status must be 'ok'.")

    minimum = event.get("minPageCount", MIN_PAGE_COUNT)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < MIN_PAGE_COUNT:
        raise InputError("minPageCount", f"minPageCount must be an integer of at least {MIN_PAGE_COUNT}.")

    # Re-validate: this JSON may be human-edited since generate_interactive_story
    # returned it, same defense-in-depth _write_draft already applies.
    _validate_interactive_story_output(output, framework["frameworkId"], language_code, minimum)

    template = output["storyTemplate"]
    story_template_id = str(uuid.uuid4())
    translation_group_id = event.get("translationGroupId") or str(uuid.uuid4())

    page_rows = [_interactive_page_item(story_template_id, page) for page in output["pages"]]

    branch_points_meta = []
    for branch_point in output.get("branchPoints") or []:
        branch_page_orders_by_option = {}
        for option_id, branch_pages in branch_point["branchPages"].items():
            branch_page_orders_by_option[option_id] = [page["pageOrder"] for page in branch_pages]
            for page in branch_pages:
                page_rows.append(_interactive_page_item(
                    story_template_id, page,
                    branch_choice_id=branch_point["choiceId"], branch_option_id=option_id,
                ))
        branch_points_meta.append({
            "choiceId": branch_point["choiceId"],
            "afterPageOrder": branch_point["afterPageOrder"],
            "reconvergesAtPageOrder": branch_point["reconvergesAtPageOrder"],
            "branchPageOrdersByOption": branch_page_orders_by_option,
        })

    template_item = {
        "storyTemplateId": story_template_id,
        "translationGroupId": translation_group_id,
        "themePackId": pack["themePackId"],
        "castMemberId": cast_member_id,
        "developmentalFramework": framework["frameworkId"],
        "languageCode": language_code,
        "title": template["title"].strip(),
        "oneLineSummary": template["oneLineSummary"].strip(),
        "isQuickStoryDefault": False,
        "catalogueStatus": "draft",
        "contentModel": "INTERACTIVE_V1",
        "entityChoices": output["entityChoices"],
        "branchPoints": branch_points_meta,
    }

    # Validate and resolve every page before the first write, same as
    # _write_draft -- draft status keeps partially-written content out of
    # all consumer paths regardless.
    story_templates_table.put_item(Item=_dynamo_safe(template_item))
    with story_template_pages_table.batch_writer() as batch:
        for page in page_rows:
            batch.put_item(Item=_dynamo_safe(page))

    return {
        "status": "ok",
        "action": "write_interactive_draft",
        "storyTemplateId": story_template_id,
        "translationGroupId": translation_group_id,
        "pageCount": len(page_rows),
        "entityChoiceCount": len(output["entityChoices"]),
        "branchPointCount": len(branch_points_meta),
        "catalogueStatus": "draft",
    }


def _interactive_page_item(story_template_id, page, branch_choice_id=None, branch_option_id=None):
    defaults = {}
    for slot_id, value in (page.get("defaultValuesBySlot") or {}).items():
        if value.get("type") == "text" and isinstance(value.get("value"), str):
            defaults[slot_id] = {"type": "text", "value": value["value"]}
        else:
            raise InputError(
                f"stage1Output.pages[{page['pageOrder']}].defaultValuesBySlot.{slot_id}",
                "Default must be a text value -- the interactive content model has no asset-based text slots.",
            )
    item = {
        "storyTemplateId": story_template_id,
        "pageOrder": page["pageOrder"],
        "textTemplate": page["textTemplate"],
        "sceneDescription": page.get("sceneDescription", ""),
        "slots": page.get("slots", []),
        "baseLayers": [],
        "defaultValuesBySlot": defaults,
    }
    if page.get("presentsChoice"):
        item["presentsChoice"] = page["presentsChoice"]
    if page.get("entityReferences"):
        item["entityReferences"] = page["entityReferences"]
    if branch_choice_id:
        item["branchChoiceId"] = branch_choice_id
        item["branchOptionId"] = branch_option_id
    return item


def _compose_illustration_spec(event):
    """Build the Stage 2 input and assembled prompt; no model call occurs
    here. Shared by generate_illustration_spec and the manual/download-only
    compose_illustration_spec action.
    """
    theme_pack_id = _required_string(event, "themePackId")
    style_id = _required_string(event, "styleId")
    if style_id not in HOUSE_STYLES:
        raise InputError("styleId", f"styleId must be one of: {', '.join(sorted(HOUSE_STYLES))}.")
    story_template_id = _required_string(event, "storyTemplateId")
    cast_member_id = _required_string(event, "castMemberId")
    cast_member = preset_cast_members_table.get_item(
        Key={"castMemberId": cast_member_id}
    ).get("Item")
    if not cast_member:
        raise InputError("castMemberId", "The selected cast member does not exist.")
    cast_already_has_base = bool(event.get("castAlreadyHasBase"))
    story = event.get("story")
    if not isinstance(story, dict) or not isinstance(story.get("storyTemplate"), dict) or not isinstance(story.get("pages"), list):
        raise InputError("story", "story must be the reviewed Stage 1 output object (storyTemplate + pages).")

    protagonist_identity_key = _slugify(cast_member["name"])
    spec_input = {
        "THEME_PACK_ID": theme_pack_id,
        "STYLE_ID": style_id,
        "STYLE_SUMMARY": house_style_summary(style_id),
        "CAST_MEMBER_ID": cast_member_id,
        "CAST_MEMBER_NAME": protagonist_identity_key,
        "CAST_ALREADY_HAS_BASE": cast_already_has_base,
        "STORY": story,
    }
    return {
        "themePackId": theme_pack_id,
        "styleId": style_id,
        "storyTemplateId": story_template_id,
        "castMemberId": cast_member_id,
        "castAlreadyHasBase": cast_already_has_base,
        "protagonistIdentityKey": protagonist_identity_key,
        "specInput": spec_input,
        "assembledPrompt": _assemble_prompt(
            STAGE_2_PROMPT_PATH, "ILLUSTRATION_SPEC_INPUT_JSON", spec_input,
            tool_name=ILLUSTRATION_SPEC_TOOL_NAME, tool_schema=ILLUSTRATION_SPEC_SCHEMA,
        ),
    }


def _compose_illustration_spec_action(event):
    composed = _compose_illustration_spec(event)
    return {
        "status": "ok",
        "action": "compose_illustration_spec",
        "mode": "manual",
        "promptVersion": STAGE_2_PROMPT_VERSION,
        "illustrationSpecInput": composed["specInput"],
        "assembledPrompt": composed["assembledPrompt"],
        "selectionContext": {
            "themePackId": composed["themePackId"],
            "styleId": composed["styleId"],
            "storyTemplateId": composed["storyTemplateId"],
            "castMemberId": composed["castMemberId"],
        },
    }


def _generate_illustration_spec(event):
    """Stage 2: turn a reviewed Stage 1 story into a STRUCTURED VISUAL PLAN.

    No prose image prompts and no pixels here -- Stage 2 only distinguishes
    NEW_IDENTITY / VARIANT_OF_IDENTITY / BACKGROUND / PROCEDURAL_EFFECT /
    STATIC_PROP and emits physical-description fields. A deterministic
    prompt compiler (prompt_compiler.py) turns this into actual image
    prompts later -- never Stage 2 itself, and never paraphrased per asset.
    """
    composed = _compose_illustration_spec(event)
    theme_pack_id = composed["themePackId"]
    style_id = composed["styleId"]
    story_template_id = composed["storyTemplateId"]
    cast_member_id = composed["castMemberId"]
    cast_already_has_base = composed["castAlreadyHasBase"]
    protagonist_identity_key = composed["protagonistIdentityKey"]
    spec_input = composed["specInput"]
    # Much larger than Stage 0/1: this emits one full spec per asset, and a
    # real story with several distinct scenes and recurring characters can
    # need 20-30+ of them -- 16000 truncated mid-JSON on real (non-test)
    # stories.
    output = _invoke_bedrock_tool(
        STAGE_2_PROMPT_PATH, "ILLUSTRATION_SPEC_INPUT_JSON", spec_input, max_tokens=64000,
        tool_name=ILLUSTRATION_SPEC_TOOL_NAME, tool_schema=ILLUSTRATION_SPEC_SCHEMA,
    )
    if output.get("status") == "refused":
        return {
            **output,
            "action": "generate_illustration_spec",
            "modelId": BEDROCK_MODEL_ID,
            "promptVersion": STAGE_2_PROMPT_VERSION,
        }
    assets = _validate_illustration_spec(output, protagonist_identity_key, cast_already_has_base)
    return {
        "status": "ok",
        "action": "generate_illustration_spec",
        "mode": "bedrock",
        "modelId": BEDROCK_MODEL_ID,
        "promptVersion": STAGE_2_PROMPT_VERSION,
        "themePackId": theme_pack_id,
        "styleId": style_id,
        "storyTemplateId": story_template_id,
        "castMemberId": cast_member_id,
        "assets": assets,
    }


_VALID_DEPTH_GROUPS = {"Foreground", "Midground", "Background"}
_CHARACTER_BIBLE_REQUIRED_FIELDS = (
    "species", "headShape", "earShape", "muzzle", "eyeConstruction",
    "bodyProportions", "silhouette", "clothing", "outline",
)


def _validate_common_asset_fields(asset, index):
    if not isinstance(asset, dict):
        raise InputError("modelOutput.assets", f"assets[{index}] must be an object.")
    if asset.get("assetKind") not in ASSET_KINDS:
        raise InputError("modelOutput.assets", f"assets[{index}].assetKind must be one of {sorted(ASSET_KINDS)}.")
    if not isinstance(asset.get("identityKey"), str) or not asset["identityKey"].strip():
        raise InputError("modelOutput.assets", f"assets[{index}].identityKey is required.")
    if not isinstance(asset.get("layerType"), str) or not asset["layerType"].strip():
        raise InputError("modelOutput.assets", f"assets[{index}].layerType is required.")
    if asset.get("depthGroup") not in _VALID_DEPTH_GROUPS:
        raise InputError("modelOutput.assets", f"assets[{index}].depthGroup must be one of {sorted(_VALID_DEPTH_GROUPS)}.")
    transform = asset.get("transform")
    if not isinstance(transform, dict) or not all(
        isinstance(transform.get(key), (int, float)) and not isinstance(transform.get(key), bool)
        for key in ("center_x", "center_y", "width", "height", "rotation_degrees")
    ):
        raise InputError("modelOutput.assets", f"assets[{index}].transform must give numeric center_x/center_y/width/height/rotation_degrees.")
    if not isinstance(asset.get("forPageOrders"), list) or not all(isinstance(v, str) for v in asset["forPageOrders"]):
        raise InputError("modelOutput.assets", f"assets[{index}].forPageOrders must be a string array.")


def _validate_character_bible(bible, index):
    if not isinstance(bible, dict):
        raise InputError("modelOutput.assets", f"assets[{index}].characterBible must be an object.")
    for field in _CHARACTER_BIBLE_REQUIRED_FIELDS:
        if not isinstance(bible.get(field), str) or not bible[field].strip():
            raise InputError("modelOutput.assets", f"assets[{index}].characterBible.{field} is required.")
    if not isinstance(bible.get("palette"), list) or not bible["palette"] or not all(isinstance(v, str) for v in bible["palette"]):
        raise InputError("modelOutput.assets", f"assets[{index}].characterBible.palette must be a non-empty string array.")


def _coerce_optional_number(asset, field, index):
    """Bedrock's JSON output isn't always faithful to the numeric fields the
    prompt asks for -- radius/falloff/opacity have shown up as quoted
    strings. Coerce those rather than letting them reach the arithmetic in
    procedural_effects.py as a str, but still refuse anything genuinely
    non-numeric.
    """
    value = asset.get(field)
    if value is None:
        return None
    if isinstance(value, bool):
        raise InputError("modelOutput.assets", f"assets[{index}].{field} must be a number.")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            pass
    raise InputError("modelOutput.assets", f"assets[{index}].{field} must be a number.")


def _validate_illustration_spec(output, protagonist_identity_key, cast_already_has_base):
    """Per-asset shape validation for all five asset kinds, then a second
    pass confirming every VARIANT_OF_IDENTITY references a real identity --
    either a NEW_IDENTITY in this same response, or the protagonist's
    already-existing identity when CAST_ALREADY_HAS_BASE is set. This is
    the check that actually enforces "no re-describing a recurring
    character from scratch": a variant with no valid identityKey is refused
    before it ever reaches image generation.
    """
    assets = output.get("assets")
    if output.get("status") != "ok" or not isinstance(assets, list) or not assets:
        raise InputError("modelOutput", "Bedrock output must contain status 'ok' and a non-empty assets array.")

    identity_keys = {protagonist_identity_key} if cast_already_has_base else set()
    protagonist_count = 0
    for index, asset in enumerate(assets):
        _validate_common_asset_fields(asset, index)
        kind = asset["assetKind"]
        if kind == "NEW_IDENTITY":
            if asset.get("kind") not in ("PROTAGONIST", "STORY_CHARACTER"):
                raise InputError("modelOutput.assets", f"assets[{index}].kind must be 'PROTAGONIST' or 'STORY_CHARACTER'.")
            if asset["kind"] == "PROTAGONIST":
                protagonist_count += 1
                if cast_already_has_base:
                    raise InputError("modelOutput.assets", f"assets[{index}] is a PROTAGONIST NEW_IDENTITY but castAlreadyHasBase is true.")
            _validate_character_bible(asset.get("characterBible"), index)
            if not isinstance(asset.get("masterPrompt"), str) or not asset["masterPrompt"].strip():
                raise InputError("modelOutput.assets", f"assets[{index}].masterPrompt is required.")
            identity_keys.add(asset["identityKey"])
        elif kind == "VARIANT_OF_IDENTITY":
            if not isinstance(asset.get("variantKey"), str) or not asset["variantKey"].strip():
                raise InputError("modelOutput.assets", f"assets[{index}].variantKey is required.")
            mutation = asset.get("mutation")
            if not isinstance(mutation, dict) or not mutation:
                raise InputError("modelOutput.assets", f"assets[{index}].mutation must be a non-empty object.")
        elif kind == "BACKGROUND":
            scene = asset.get("scene")
            if not isinstance(scene, dict) or not scene:
                raise InputError("modelOutput.assets", f"assets[{index}].scene must be a non-empty object.")
        elif kind == "PROCEDURAL_EFFECT":
            if asset.get("effectType") != "radial_glow":
                raise InputError("modelOutput.assets", f"assets[{index}].effectType must be 'radial_glow'.")
            if not isinstance(asset.get("color"), str) or not asset["color"].strip():
                raise InputError("modelOutput.assets", f"assets[{index}].color is required.")
            try:
                procedural_effects.resolve_glow_color(asset["color"])
            except ValueError as error:
                raise InputError("modelOutput.assets", f"assets[{index}].color: {error}") from error
            for field in ("radius", "falloff", "opacity"):
                asset[field] = _coerce_optional_number(asset, field, index)
        elif kind == "STATIC_PROP":
            if not isinstance(asset.get("physicalPrompt"), str) or not asset["physicalPrompt"].strip():
                raise InputError("modelOutput.assets", f"assets[{index}].physicalPrompt is required.")

    if protagonist_count > 1:
        raise InputError("modelOutput.assets", "At most one PROTAGONIST NEW_IDENTITY is allowed.")

    for index, asset in enumerate(assets):
        if asset["assetKind"] == "VARIANT_OF_IDENTITY" and asset["identityKey"] not in identity_keys:
            raise InputError(
                "modelOutput.assets",
                f"assets[{index}] is a VARIANT_OF_IDENTITY for '{asset['identityKey']}', which has no "
                "matching NEW_IDENTITY in this response (and castAlreadyHasBase does not cover it).",
            )
    return assets


def _generate_illustrations(event):
    """Generate every asset in a reviewed Stage 2 plan.

    Masters (NEW_IDENTITY) and backgrounds run synchronously first, in this
    same invocation -- variants can't be conditioned on a master that
    doesn't exist yet. Once those exist, variants/effects/static props (each
    independent of one another) fan out as async jobs exactly as before.
    """
    theme_pack_id = _required_string(event, "themePackId")
    style_id = _required_string(event, "styleId")
    if style_id not in HOUSE_STYLES:
        raise InputError("styleId", f"styleId must be one of: {', '.join(sorted(HOUSE_STYLES))}.")
    story_template_id = _required_string(event, "storyTemplateId")
    cast_member_id = _required_string(event, "castMemberId")
    cast_member = preset_cast_members_table.get_item(Key={"castMemberId": cast_member_id}).get("Item")
    if not cast_member:
        raise InputError("castMemberId", "The selected cast member does not exist.")
    force_regenerate = bool(event.get("forceRegenerate"))

    assets = event.get("assets")
    if not isinstance(assets, list) or not assets:
        raise InputError("assets", "assets must be a non-empty array of reviewed illustration-plan entries.")
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict) or asset.get("assetKind") not in ASSET_KINDS:
            raise InputError("assets", f"assets[{index}].assetKind must be one of {sorted(ASSET_KINDS)}.")
    # Set only when this job itself was enqueued through the API (see
    # story_production_api's Payload); propagated onto each child job so the
    # same user can poll them, matching the requestedBy check GET uses.
    requested_by = event.get("_requestedBy")

    protagonist_identity_key = _slugify(cast_member["name"])
    house_style_ref_b64, house_style_ref_fingerprint = _ensure_house_style_reference(
        theme_pack_id, style_id
    )

    identity_scopes = {protagonist_identity_key: {"scopeType": "CAST_MEMBER", "scopeId": cast_member_id}}
    master_assets = {}

    # Phase 1: NEW_IDENTITY masters, synchronous, in-order.
    for asset in assets:
        if asset.get("assetKind") != "NEW_IDENTITY":
            continue
        identity_key = asset["identityKey"]
        scope_type = "CAST_MEMBER" if asset["kind"] == "PROTAGONIST" else "STORY"
        scope_id = cast_member_id if scope_type == "CAST_MEMBER" else story_template_id
        identity_scopes[identity_key] = {"scopeType": scope_type, "scopeId": scope_id}
        master_assets[identity_key] = _ensure_master_character(
            scope_type, scope_id, identity_key, style_id, asset["layerType"],
            asset["characterBible"], asset["masterPrompt"],
            house_style_ref_b64, house_style_ref_fingerprint, force_regenerate,
        )

    # A variant may reference the protagonist's identity without a
    # NEW_IDENTITY in this batch (castAlreadyHasBase) -- its master must
    # already be persisted from an earlier generate_illustrations call.
    for asset in assets:
        if asset.get("assetKind") != "VARIANT_OF_IDENTITY" or asset["identityKey"] in master_assets:
            continue
        scope = identity_scopes.get(asset["identityKey"])
        if not scope:
            raise InputError("assets", f"No identity scope known for '{asset['identityKey']}'.")
        existing_master = _get_asset(_deterministic_asset_id(
            scope["scopeType"], scope["scopeId"], asset["identityKey"], style_id, "master"
        ))
        if not existing_master:
            raise InputError(
                "assets",
                f"No master asset exists yet for identity '{asset['identityKey']}'; "
                "generate its NEW_IDENTITY entry first.",
            )
        master_assets[asset["identityKey"]] = existing_master

    # Phase 1b: BACKGROUND, synchronous (reuses the house-style reference).
    background_assets = {}
    for asset in assets:
        if asset.get("assetKind") != "BACKGROUND":
            continue
        background_assets[asset["identityKey"]] = _ensure_background(
            "STORY", story_template_id, asset["identityKey"], style_id, asset["scene"],
            house_style_ref_b64, house_style_ref_fingerprint, force_regenerate,
        )

    # Phase 2: everything else fans out async, same job/poll pattern as before.
    # Batched (see ASSET_JOB_BATCH_SIZE) so Bedrock never sees more than a
    # handful of concurrent InvokeModel calls from this one story.
    jobs = []
    fanout_assets = [
        asset for asset in assets
        if asset.get("assetKind") in ("VARIANT_OF_IDENTITY", "PROCEDURAL_EFFECT", "STATIC_PROP")
    ]
    for batch_start in range(0, len(fanout_assets), ASSET_JOB_BATCH_SIZE):
        batch = fanout_assets[batch_start:batch_start + ASSET_JOB_BATCH_SIZE]
        for asset in batch:
            kind = asset["assetKind"]
            job_id = str(uuid.uuid4())
            now = int(time.time())
            job_item = {
                "jobId": job_id, "action": "generate_asset_image",
                "status": "queued", "createdAt": now, "expiresAt": now + 86400,
            }
            if requested_by:
                job_item["requestedBy"] = requested_by
            jobs_table.put_item(Item=job_item)
            payload = {
                "_jobId": job_id, "action": "generate_asset_image",
                "themePackId": theme_pack_id, "styleId": style_id,
                "storyTemplateId": story_template_id, "forceRegenerate": force_regenerate,
                "asset": asset,
            }
            if kind == "VARIANT_OF_IDENTITY":
                payload["masterAssetId"] = master_assets[asset["identityKey"]]["assetId"]
            lambda_client.invoke(
                FunctionName=SELF_FUNCTION_NAME, InvocationType="Event",
                Payload=json.dumps(payload).encode(),
            )
            jobs.append({
                "jobId": job_id, "assetKind": kind, "identityKey": asset["identityKey"],
                "variantKey": asset.get("variantKey"),
            })
        if batch_start + ASSET_JOB_BATCH_SIZE < len(fanout_assets):
            time.sleep(ASSET_JOB_BATCH_DELAY_SECONDS)

    logger.info(
        "generate_illustrations mastersReady=%d backgroundsReady=%d jobsEnqueued=%d themePackId=%s styleId=%s",
        len(master_assets), len(background_assets), len(jobs), theme_pack_id, style_id,
    )
    return {
        "status": "ok",
        "action": "generate_illustrations",
        "themePackId": theme_pack_id,
        "styleId": style_id,
        "masters": [
            {"identityKey": k, "assetId": v["assetId"], "cdnUrl": _cdn_url(v["cdnKey"])}
            for k, v in master_assets.items()
        ],
        "backgrounds": [
            {"identityKey": k, "assetId": v["assetId"], "cdnUrl": _cdn_url(v["cdnKey"])}
            for k, v in background_assets.items()
        ],
        "jobs": jobs,
    }


def _generate_asset_image(event):
    """Worker: render one VARIANT_OF_IDENTITY / PROCEDURAL_EFFECT /
    STATIC_PROP asset (masters and backgrounds are generated synchronously
    in generate_illustrations and never reach this worker).
    """
    theme_pack_id = _required_string(event, "themePackId")
    style_id = _required_string(event, "styleId")
    story_template_id = _required_string(event, "storyTemplateId")
    force_regenerate = bool(event.get("forceRegenerate"))
    asset = event.get("asset")
    if not isinstance(asset, dict) or asset.get("assetKind") not in ASSET_KINDS:
        raise InputError("asset", f"asset.assetKind must be one of {sorted(ASSET_KINDS)}.")
    kind = asset["assetKind"]
    logger.info(
        "generate_asset_image start assetKind=%s identityKey=%s variantKey=%s",
        kind, asset.get("identityKey"), asset.get("variantKey"),
    )

    if kind == "VARIANT_OF_IDENTITY":
        master_asset_id = _required_string(event, "masterAssetId")
        master = _get_asset(master_asset_id)
        if not master:
            raise InputError("masterAssetId", f"Master asset '{master_asset_id}' does not exist.")
        result = _ensure_character_variant(
            master["scopeType"], master["scopeId"], asset["identityKey"], asset["variantKey"],
            style_id, asset["layerType"], master, asset["mutation"], force_regenerate,
        )
    elif kind == "PROCEDURAL_EFFECT":
        result = _ensure_procedural_effect(
            "STORY", story_template_id, asset["identityKey"], style_id,
            asset["effectType"], asset["color"], asset.get("radius"),
            asset.get("falloff"), asset.get("opacity"), force_regenerate,
        )
    elif kind == "STATIC_PROP":
        house_style_ref_b64, house_style_ref_fingerprint = _ensure_house_style_reference(
            theme_pack_id, style_id
        )
        result = _ensure_static_prop(
            "STORY", story_template_id, asset["identityKey"], style_id, asset["layerType"],
            asset["physicalPrompt"], house_style_ref_b64, house_style_ref_fingerprint, force_regenerate,
        )
    else:
        raise InputError("asset.assetKind", f"generate_asset_image does not handle '{kind}' directly.")

    logger.info("generate_asset_image done assetId=%s cdnKey=%s", result["assetId"], result["cdnKey"])
    return {
        "status": "ok",
        "action": "generate_asset_image",
        "assetId": result["assetId"],
        "cdnKey": result["cdnKey"],
        "cdnUrl": _cdn_url(result["cdnKey"]),
        "identityKey": asset.get("identityKey"),
        "variantKey": asset.get("variantKey"),
    }


def _cdn_url(cdn_key):
    return f"https://{CDN_DOMAIN}/{cdn_key}" if CDN_DOMAIN else None


def _slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "identity"


def _deterministic_asset_id(scope_type, scope_id, identity_key, style_id, variant_key):
    """The canonical identity of an asset -- stable across regenerations.
    Deliberately excludes anything about HOW the image was produced (that's
    generationFingerprint's job) so a prompt/style/provider change updates
    the existing canonical row instead of orphaning it under a new id.
    """
    raw = f"{scope_type}|{scope_id}|{identity_key}|{style_id}|{variant_key}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _compute_fingerprint(*parts):
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_asset(asset_id):
    return assets_table.get_item(Key={"assetId": asset_id}).get("Item")


def _fetch_asset_image_b64(asset):
    obj = s3_client.get_object(Bucket=CATALOGUE_ASSETS_BUCKET, Key=asset["cdnKey"])
    return base64.b64encode(obj["Body"].read()).decode()


def _ensure_generated_asset(
    scope_type, scope_id, identity_key, variant_key, style_id, role, layer_type,
    generate_fn, fingerprint_inputs, persist_extra, force_regenerate,
):
    """Shared idempotent generate-or-reuse path for every asset kind.

    Canonical assetId is deterministic and never changes. generationFingerprint
    covers everything that actually affects the rendered output (compiled
    prompt text, provider/model/fidelity, and -- for variants -- the
    referenced master's own fingerprint, so a changed master cascades into
    stale variants instead of them silently keeping the old identity). A
    fingerprint match reuses the existing row with no new generation call.

    Failure safety: the new image is generated and uploaded to a
    revision-suffixed S3 key BEFORE the Assets row is written, so a failed
    generation never leaves the canonical row pointing at a missing object,
    and the previously-valid asset stays usable the whole time.
    """
    asset_id = _deterministic_asset_id(scope_type, scope_id, identity_key, style_id, variant_key)
    fingerprint = _compute_fingerprint(*fingerprint_inputs)
    existing = _get_asset(asset_id)
    if existing and not force_regenerate and existing.get("generationFingerprint") == fingerprint and existing.get("cdnKey"):
        logger.info(
            "asset reuse assetId=%s role=%s identityKey=%s variantKey=%s revision=%s",
            asset_id, role, identity_key, variant_key, existing.get("generationRevision"),
        )
        return existing

    logger.info(
        "asset generate assetId=%s role=%s identityKey=%s variantKey=%s forceRegenerate=%s",
        asset_id, role, identity_key, variant_key, force_regenerate,
    )
    image_bytes, provider_meta = generate_fn()
    revision = (existing.get("generationRevision", 0) if existing else 0) + 1
    cdn_key = (
        f"illustrations/{scope_type.lower()}/{scope_id}/{identity_key}/"
        f"{style_id}/{variant_key}-{fingerprint[:12]}.png"
    )
    # Upload before touching the Assets row: if anything above raised, the
    # existing row (if any) is untouched and still points at a valid object.
    s3_client.put_object(
        Bucket=CATALOGUE_ASSETS_BUCKET, Key=cdn_key, Body=image_bytes, ContentType="image/png",
    )
    now = int(time.time())
    item = {
        "assetId": asset_id,
        "scopeType": scope_type, "scopeId": scope_id,
        "identityKey": identity_key, "variantKey": variant_key,
        "styleId": style_id, "role": role, "layerType": layer_type,
        "generationFingerprint": fingerprint, "generationRevision": revision,
        "houseStyleVersion": HOUSE_STYLE_VERSION, "promptCompilerVersion": PROMPT_COMPILER_VERSION,
        "cdnKey": cdn_key,
        "createdAt": existing.get("createdAt", now) if existing else now,
        "updatedAt": now,
        **provider_meta,
        **persist_extra,
    }
    if role == "MASTER_CHARACTER" and scope_type == "CAST_MEMBER":
        # story_preview's existing compositor (_cast_base_assets) already
        # queries cast pieces by this key -- keep writing it so that
        # long-standing read path picks up real generated art for the
        # first time, with no change to story_preview itself.
        item["castMemberStyleKey"] = f"{scope_id}#{style_id}"
    # boto3's DynamoDB resource layer rejects native floats outright (e.g.
    # fidelity, or falloff/opacity in a procedural effect's
    # generationSettings) -- convert on a copy so the in-memory item
    # returned to callers (compiled into later prompts/fingerprints) keeps
    # plain floats, not Decimals leaking into JSON responses elsewhere.
    assets_table.put_item(Item=_dynamo_safe(item))
    return item


def _dynamo_safe(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _dynamo_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dynamo_safe(v) for v in value]
    return value


def _ensure_master_character(
    scope_type, scope_id, identity_key, style_id, layer_type,
    character_bible, master_prompt, house_style_ref_b64, house_style_ref_fingerprint,
    force_regenerate,
):
    compiled_prompt, negative = compile_master_prompt(style_id, character_bible, master_prompt)
    bible_fingerprint = hashlib.sha256(
        json.dumps(character_bible, sort_keys=True).encode()
    ).hexdigest()
    fingerprint_inputs = (
        "stability", STYLE_GUIDE_MODEL_ID, MASTER_FIDELITY, compiled_prompt,
        house_style_ref_fingerprint, bible_fingerprint, HOUSE_STYLE_VERSION, PROMPT_COMPILER_VERSION,
    )

    def generate():
        styled_b64 = _invoke_style_guide(compiled_prompt, house_style_ref_b64, fidelity=MASTER_FIDELITY, negative=negative)
        final_bytes = base64.b64decode(_invoke_remove_background(styled_b64))
        return final_bytes, {
            "provider": "stability", "providerModel": STYLE_GUIDE_MODEL_ID, "fidelity": MASTER_FIDELITY,
            "compiledPrompt": compiled_prompt, "negativeConstraints": negative,
            "generationSettings": {"referenceKind": "houseStyle"},
            "generationType": "AI_MASTER",
            "referenceAssetId": None, "referenceGenerationFingerprint": house_style_ref_fingerprint,
        }

    return _ensure_generated_asset(
        scope_type, scope_id, identity_key, "master", style_id, "MASTER_CHARACTER", layer_type,
        generate, fingerprint_inputs, {"characterBible": character_bible}, force_regenerate,
    )


def _ensure_character_variant(
    scope_type, scope_id, identity_key, variant_key, style_id, layer_type,
    master_asset, mutation, force_regenerate,
):
    compiled_prompt, negative = compile_variant_prompt(style_id, master_asset["characterBible"], mutation)
    fingerprint_inputs = (
        "stability", STYLE_GUIDE_MODEL_ID, VARIANT_FIDELITY, compiled_prompt,
        master_asset["assetId"], master_asset["generationFingerprint"],
        HOUSE_STYLE_VERSION, PROMPT_COMPILER_VERSION,
    )

    def generate():
        master_b64 = _fetch_asset_image_b64(master_asset)
        styled_b64 = _invoke_style_guide(compiled_prompt, master_b64, fidelity=VARIANT_FIDELITY, negative=negative)
        final_bytes = base64.b64decode(_invoke_remove_background(styled_b64))
        return final_bytes, {
            "provider": "stability", "providerModel": STYLE_GUIDE_MODEL_ID, "fidelity": VARIANT_FIDELITY,
            "compiledPrompt": compiled_prompt, "negativeConstraints": negative,
            "generationSettings": {"referenceKind": "masterAsset"},
            "generationType": "AI_VARIANT",
            "referenceAssetId": master_asset["assetId"],
            "referenceGenerationFingerprint": master_asset["generationFingerprint"],
        }

    return _ensure_generated_asset(
        scope_type, scope_id, identity_key, variant_key, style_id, "CHARACTER_VARIANT", layer_type,
        generate, fingerprint_inputs,
        {"masterAssetId": master_asset["assetId"], "mutation": mutation},
        force_regenerate,
    )


def _ensure_background(
    scope_type, scope_id, identity_key, style_id, scene,
    house_style_ref_b64, house_style_ref_fingerprint, force_regenerate,
):
    compiled_prompt, negative = compile_background_prompt(style_id, scene)
    fingerprint_inputs = (
        "stability", STYLE_GUIDE_MODEL_ID, None, compiled_prompt,
        house_style_ref_fingerprint, HOUSE_STYLE_VERSION, PROMPT_COMPILER_VERSION,
    )

    def generate():
        # Full fidelity, unlike characters: a background should match the
        # reference's whole scene, not just its stroke/color style.
        styled_b64 = _invoke_style_guide(compiled_prompt, house_style_ref_b64, negative=negative)
        return base64.b64decode(styled_b64), {
            "provider": "stability", "providerModel": STYLE_GUIDE_MODEL_ID, "fidelity": None,
            "compiledPrompt": compiled_prompt, "negativeConstraints": negative,
            "generationSettings": {"referenceKind": "houseStyle"},
            "generationType": "AI_BACKGROUND",
            "referenceAssetId": None, "referenceGenerationFingerprint": house_style_ref_fingerprint,
        }

    return _ensure_generated_asset(
        scope_type, scope_id, identity_key, "master", style_id, "BACKGROUND", BACKGROUND_LAYER_TYPE,
        generate, fingerprint_inputs, {}, force_regenerate,
    )


def _ensure_static_prop(
    scope_type, scope_id, identity_key, style_id, layer_type, physical_prompt,
    house_style_ref_b64, house_style_ref_fingerprint, force_regenerate,
):
    compiled_prompt, negative = compile_static_prop_prompt(style_id, physical_prompt)
    fingerprint_inputs = (
        "stability", STYLE_GUIDE_MODEL_ID, STATIC_PROP_FIDELITY, compiled_prompt,
        house_style_ref_fingerprint, HOUSE_STYLE_VERSION, PROMPT_COMPILER_VERSION,
    )

    def generate():
        styled_b64 = _invoke_style_guide(compiled_prompt, house_style_ref_b64, fidelity=STATIC_PROP_FIDELITY, negative=negative)
        final_bytes = base64.b64decode(_invoke_remove_background(styled_b64))
        return final_bytes, {
            "provider": "stability", "providerModel": STYLE_GUIDE_MODEL_ID, "fidelity": STATIC_PROP_FIDELITY,
            "compiledPrompt": compiled_prompt, "negativeConstraints": negative,
            "generationSettings": {"referenceKind": "houseStyle"},
            "generationType": "AI_BACKGROUND",
            "referenceAssetId": None, "referenceGenerationFingerprint": house_style_ref_fingerprint,
        }

    return _ensure_generated_asset(
        scope_type, scope_id, identity_key, "master", style_id, "STATIC_PROP", layer_type,
        generate, fingerprint_inputs, {}, force_regenerate,
    )


def _ensure_procedural_effect(
    scope_type, scope_id, identity_key, style_id, effect_type, color,
    radius, falloff, opacity, force_regenerate,
):
    if effect_type != "radial_glow":
        raise InputError("effectType", f"Unsupported procedural effectType '{effect_type}'.")
    radius = radius or 128
    falloff = falloff or 2.0
    opacity = opacity or 0.85
    fingerprint_inputs = ("procedural", effect_type, color, radius, falloff, opacity)

    def generate():
        # No Bedrock call at all -- this is exactly what makes a glow
        # deterministic instead of coming back as a decorative medallion.
        final_bytes = procedural_effects.generate_radial_glow(
            color, size=max(int(radius) * 2, 64), falloff=falloff, opacity=opacity,
        )
        return final_bytes, {
            "provider": "procedural", "providerModel": None, "fidelity": None,
            "compiledPrompt": None, "negativeConstraints": [],
            "generationSettings": {
                "effectType": effect_type, "color": color,
                "radius": radius, "falloff": falloff, "opacity": opacity,
            },
            "generationType": "PROCEDURAL",
            "referenceAssetId": None, "referenceGenerationFingerprint": None,
        }

    return _ensure_generated_asset(
        scope_type, scope_id, identity_key, "master", style_id, "PROCEDURAL_EFFECT", "prop_light",
        generate, fingerprint_inputs, {}, force_regenerate,
    )


def _ensure_house_style_reference(theme_pack_id, style_id):
    """Return (base64 image, content fingerprint) for the (themePackId,
    styleId) house-style reference, generating and caching it in S3 on first
    use. The reference prompt itself is always compiled from the locked
    global + style bibles and a fixed neutral reference scene -- never
    authored by a person, so there is nothing for a caller to supply here.

    The cache key includes HOUSE_STYLE_VERSION, so bumping it (any global or
    style-specific bible edit) invalidates the cached reference image itself,
    not just the masters/backgrounds computed from it.

    The fingerprint is a hash of the actual image bytes, so if this
    reference is ever regenerated with different content, every master and
    background conditioned on it naturally computes a different
    generationFingerprint on their next check and is treated as stale.

    Concurrent first-use jobs may each generate one; whichever write lands
    last wins, an accepted simplification rather than cross-job locking for
    a one-time cost.
    """
    key = f"illustrations/house-style-refs/{theme_pack_id}/{style_id}/v{HOUSE_STYLE_VERSION}.png"
    try:
        existing = s3_client.get_object(Bucket=CATALOGUE_ASSETS_BUCKET, Key=key)
        image_bytes = existing["Body"].read()
        logger.info("house-style reference cache hit key=%s", key)
        return base64.b64encode(image_bytes).decode(), hashlib.sha256(image_bytes).hexdigest()
    except s3_client.exceptions.NoSuchKey:
        logger.info("house-style reference cache miss key=%s", key)

    reference_prompt, negative = compile_house_style_reference_prompt(style_id)
    started = time.monotonic()
    response = bedrock_runtime_house_style_images.invoke_model(
        modelId=HOUSE_STYLE_MODEL_ID,
        body=json.dumps({
            "prompt": reference_prompt,
            "negative_prompt": ", ".join(negative),
            "aspect_ratio": "1:1",
            "mode": "text-to-image",
            "output_format": "png",
        }),
        contentType="application/json",
        accept="application/json",
    )
    logger.info("house-style reference generated elapsedSec=%.1f", time.monotonic() - started)
    result = json.loads(response["body"].read())
    image_bytes = base64.b64decode(result["images"][0])
    s3_client.put_object(
        Bucket=CATALOGUE_ASSETS_BUCKET, Key=key, Body=image_bytes, ContentType="image/png",
    )
    return base64.b64encode(image_bytes).decode(), hashlib.sha256(image_bytes).hexdigest()


def _invoke_style_guide(prompt, reference_b64, fidelity=None, negative=None):
    body = {"prompt": prompt, "image": reference_b64, "output_format": "png"}
    if fidelity is not None:
        body["fidelity"] = fidelity
    if negative:
        # Every caller computes this (house-style prohibitions, "no other
        # characters", etc.) but it was never actually sent -- confirmed
        # live: a house-style reference asked for one ambiguous woodland
        # creature on a plain background came back as three named human
        # characters in a full scene, because nothing was ever telling the
        # model what to exclude.
        body["negative_prompt"] = ", ".join(negative)
    started = time.monotonic()
    response = bedrock_runtime_images.invoke_model(
        modelId=STYLE_GUIDE_MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    logger.info("style-guide done elapsedSec=%.1f fidelity=%s", time.monotonic() - started, fidelity)
    return json.loads(response["body"].read())["images"][0]


def _invoke_remove_background(image_b64):
    started = time.monotonic()
    response = bedrock_runtime_images.invoke_model(
        modelId=REMOVE_BG_MODEL_ID,
        body=json.dumps({"image": image_b64, "output_format": "png"}),
        contentType="application/json",
        accept="application/json",
    )
    logger.info("remove-background done elapsedSec=%.1f", time.monotonic() - started)
    return json.loads(response["body"].read())["images"][0]


def _load_context(event):
    theme_pack_id = _required_string(event, "themePackId")
    framework_id = _required_string(event, "frameworkId")
    language_code = _required_string(event, "languageCode")
    if not LANGUAGE_CODE_RE.fullmatch(language_code):
        raise InputError("languageCode", "languageCode must be a BCP-47-style language tag such as 'en' or 'fr-CA'.")

    pack = theme_packs_table.get_item(Key={"themePackId": theme_pack_id}).get("Item")
    if not pack:
        raise InputError("themePackId", "The selected theme pack does not exist.")
    framework = developmental_frameworks_table.get_item(Key={"frameworkId": framework_id}).get("Item")
    if not framework:
        raise InputError("frameworkId", "The selected developmental framework does not exist.")
    if not framework.get("narrativeGuidance"):
        raise InputError("frameworkId", "The selected framework has no narrative guidance.")
    allowed = pack.get("developmentalFrameworks")
    if allowed and framework_id not in allowed:
        raise InputError("frameworkId", "The selected framework is not enabled for this theme pack.")
    return pack, framework, language_code


def _required_string(event, field):
    value = event.get(field)
    if not isinstance(value, str) or not value.strip():
        raise InputError(field, f"{field} is required and must be a non-empty string.")
    return value.strip()


def _cast_members(theme_pack_id):
    members = preset_cast_members_table.scan().get("Items", [])
    return [
        {
            "castMemberId": member["castMemberId"],
            "name": member["name"],
            "personalityDescription": member.get("personalityDescription", ""),
            "catalogueStatus": member.get("catalogueStatus", "draft"),
        }
        for member in members
        if not member.get("availableThemePacks") or theme_pack_id in member["availableThemePacks"]
    ]


def _creative_brief(event, framework):
    direct = event.get("creativeBrief")
    if direct is not None:
        if not isinstance(direct, str):
            raise InputError("creativeBrief", "creativeBrief must be a string.")
        return direct.strip() or None

    answers = event.get("creativeBriefAnswers") or {}
    if not isinstance(answers, dict):
        raise InputError("creativeBriefAnswers", "creativeBriefAnswers must be keyed by questionId.")
    parts = []
    for question in framework.get("creativeBriefQuestions", []):
        answer = answers.get(question.get("questionId"))
        if answer is not None and not isinstance(answer, str):
            raise InputError("creativeBriefAnswers", "Every creative brief answer must be a string.")
        if answer and answer.strip():
            parts.append(answer.strip())
    return " ".join(parts) or None


def _brief_answers(event, framework):
    answers = event.get("creativeBriefAnswers") or {}
    if not isinstance(answers, dict):
        raise InputError("creativeBriefAnswers", "creativeBriefAnswers must be keyed by questionId.")
    known_ids = {
        question.get("questionId") for question in framework.get("creativeBriefQuestions", [])
    }
    result = []
    for question_id, answer in answers.items():
        if question_id not in known_ids:
            raise InputError("creativeBriefAnswers", f"Unknown framework questionId '{question_id}'.")
        if not isinstance(answer, str):
            raise InputError("creativeBriefAnswers", "Every creative brief answer must be a string.")
        if answer.strip():
            result.append({"questionId": question_id, "answer": answer.strip()})
    return result


def _selected_concept_brief(event):
    concept = event.get("selectedConcept")
    if concept is None:
        return None
    if not isinstance(concept, dict):
        raise InputError("selectedConcept", "selectedConcept must be one Concept Studio concept object.")
    required = (
        "workingTitle", "toddlerHook", "emotionalPromise", "centralSituation",
        "resolution", "familyConnection", "bedtimeEnding",
    )
    for field in required:
        if not isinstance(concept.get(field), str) or not concept[field].strip():
            raise InputError("selectedConcept", f"selectedConcept.{field} is required.")
    # Preserve the selected concept's structure in a compact string instead
    # of allowing Stage 1 to reinterpret a vague title as a new premise.
    labels = (
        ("Working title", "workingTitle"),
        ("Toddler hook", "toddlerHook"),
        ("Emotional promise", "emotionalPromise"),
        ("Central situation", "centralSituation"),
        ("Resolution", "resolution"),
        ("Repeatable element", "repeatableElement"),
        ("Family connection", "familyConnection"),
        ("Personalization moments", "personalizationMoments"),
        ("Bedtime ending", "bedtimeEnding"),
    )
    parts = []
    for label, field in labels:
        value = concept.get(field)
        if isinstance(value, list):
            # Each item is already a full sentence -- a bare ", ".join
            # produces "...quality., The child's name..." when an item ends
            # in its own period (confirmed live). Normalize each item to end
            # in exactly one period before joining as separate sentences.
            value = " ".join(
                item if re.search(r'[.!?]["\'’”]?$', item) else f"{item}."
                for item in (str(entry).strip() for entry in value) if item
            )
        if value:
            parts.append(f"{label}: {value}")
    return "; ".join(parts)


def _existing_premises(theme_pack_id, framework_id, language_code):
    result = story_templates_table.query(
        IndexName="byThemePack",
        KeyConditionExpression="themePackId = :tid",
        ExpressionAttributeValues={":tid": theme_pack_id},
    )
    return [
        {"title": item["title"], "oneLineSummary": item.get("oneLineSummary", "")}
        for item in result.get("Items", [])
        if item.get("developmentalFramework") == framework_id
        and item.get("languageCode", "en") == language_code
    ]


def _slot_vocabulary(theme_pack_id):
    result = assets_table.query(
        IndexName="byThemePack",
        KeyConditionExpression="themePackId = :tid",
        ExpressionAttributeValues={":tid": theme_pack_id},
    )
    by_tag = {}
    for asset in result.get("Items", []):
        tag = asset.get("slotTag")
        if not tag or asset.get("layerType") in ("cast_base", "cast_expression"):
            continue
        entry = by_tag.setdefault(tag, {
            "slotTag": tag,
            "layerType": asset.get("layerType"),
            "sampleDisplayLabels": [],
        })
        label = _display_label(asset, "en")
        if label and label not in entry["sampleDisplayLabels"]:
            entry["sampleDisplayLabels"].append(label)
    return sorted(by_tag.values(), key=lambda entry: entry["slotTag"])


def _name_suggestions(pack, language_code):
    result = []
    for slot_tag, value in pack.get("nameSuggestions", {}).items():
        if isinstance(value, dict):
            suggestions = value.get(language_code, [])
        else:
            suggestions = value if language_code == "en" else []
        result.append({"slotTag": slot_tag, "suggestions": suggestions})
    return sorted(result, key=lambda entry: entry["slotTag"])


def _display_label(asset, language_code):
    labels = asset.get("displayLabel")
    if isinstance(labels, dict):
        return labels.get(language_code) or labels.get("en")
    return labels


_DASH_CHARS = ("—", "–")  # em dash, en dash -- prompt bans both; stop relying on the model to comply.
_SLOT_ID_RE_CACHE = {}


def _slot_id_pattern(slot_tag):
    pattern = _SLOT_ID_RE_CACHE.get(slot_tag)
    if pattern is None:
        pattern = re.compile(rf"^{re.escape(slot_tag)}_slot(_\d+)?$")
        _SLOT_ID_RE_CACHE[slot_tag] = pattern
    return pattern


def _validate_output(template, pages, framework_id, language_code, minimum, new_slot_tags_needing_art=None):
    if not isinstance(template, dict):
        raise InputError("stage1Output.storyTemplate", "storyTemplate must be an object.")
    for field in ("title", "oneLineSummary"):
        if not isinstance(template.get(field), str) or not template[field].strip():
            raise InputError(f"stage1Output.storyTemplate.{field}", f"{field} must be a non-empty string.")
    if template.get("developmentalFramework") != framework_id:
        raise InputError("stage1Output.storyTemplate.developmentalFramework", "The output framework does not match frameworkId.")
    if template.get("languageCode") != language_code:
        raise InputError("stage1Output.storyTemplate.languageCode", "The output language does not match languageCode.")
    if not isinstance(pages, list) or len(pages) < minimum:
        raise InputError("stage1Output.pages", f"At least {minimum} pages are required.")

    expected_orders = [f"{index:04d}" for index in range(1, len(pages) + 1)]
    actual_orders = [page.get("pageOrder") if isinstance(page, dict) else None for page in pages]
    if actual_orders != expected_orders:
        raise InputError("stage1Output.pages.pageOrder", "Pages must be ordered consecutively from '0001'.")

    new_vocab_tags = set()
    for page in pages:
        new_vocab_tags |= _validate_page(page)

    if new_slot_tags_needing_art:
        if not isinstance(new_slot_tags_needing_art, list):
            raise InputError("stage1Output.newSlotTagsNeedingArt", "newSlotTagsNeedingArt must be an array.")
        for index, entry in enumerate(new_slot_tags_needing_art):
            slot_tag = entry.get("slotTag") if isinstance(entry, dict) else None
            if slot_tag not in new_vocab_tags:
                # A CONTROLLED_VOCAB_WITH_OVERRIDE (free-text) slot has
                # nothing to illustrate -- confirmed live: a child's-name
                # text slot was listed here with layerType "text_overlay",
                # which makes no sense for typed text.
                raise InputError(
                    "stage1Output.newSlotTagsNeedingArt",
                    f"newSlotTagsNeedingArt[{index}] references slotTag '{slot_tag}', which is not a new "
                    "CONTROLLED_VOCAB slot declared on any page. Only CONTROLLED_VOCAB slots need art; "
                    "CONTROLLED_VOCAB_WITH_OVERRIDE (free-text) slots never belong here.",
                )


def _validate_page(page):
    """Returns the set of slotTags this page declares as new CONTROLLED_VOCAB
    vocabulary, for newSlotTagsNeedingArt cross-checking in _validate_output.
    """
    order = page["pageOrder"]
    text = page.get("textTemplate")
    if not isinstance(text, str) or not text.strip():
        raise InputError(f"stage1Output.pages[{order}].textTemplate", "textTemplate must be non-empty.")
    if any(char in text for char in _DASH_CHARS):
        raise InputError(
            f"stage1Output.pages[{order}].textTemplate",
            "textTemplate must not contain an em dash (—) or en dash (–); "
            "use periods, commas, colons, or parentheses instead.",
        )
    slots = page.get("slots") or []
    if not isinstance(slots, list):
        raise InputError(f"stage1Output.pages[{order}].slots", "slots must be an array.")
    slot_ids = set()
    new_vocab_tags = set()
    for slot in slots:
        slot_id = slot.get("slotId") if isinstance(slot, dict) else None
        if not slot_id or slot_id in slot_ids:
            raise InputError(f"stage1Output.pages[{order}].slots", "Every slotId must be non-empty and unique on its page.")
        slot_ids.add(slot_id)
        if slot.get("slotType") not in VALID_SLOT_TYPES:
            raise InputError(f"stage1Output.pages[{order}].slots.{slot_id}", "Unsupported slotType.")
        slot_tag = slot.get("slotTag")
        if not slot_tag:
            raise InputError(f"stage1Output.pages[{order}].slots.{slot_id}", "slotTag is required.")
        if not _slot_id_pattern(slot_tag).match(slot_id):
            raise InputError(
                f"stage1Output.pages[{order}].slots.{slot_id}",
                f"slotId '{slot_id}' must be '{slot_tag}_slot', or '{slot_tag}_slot_2' etc. for a repeat "
                "on the same page -- it must not drift from its slotTag.",
            )
        if f"{{{{{slot_id}}}}}" not in text:
            raise InputError(f"stage1Output.pages[{order}].textTemplate", f"Missing placeholder for slotId '{slot_id}'.")
        if slot.get("isNewSlotTag") and slot.get("slotType") == "CONTROLLED_VOCAB":
            new_vocab_tags.add(slot_tag)
    defaults = page.get("defaultValuesBySlot") or {}
    if not isinstance(defaults, dict) or any(key not in slot_ids for key in defaults):
        raise InputError(f"stage1Output.pages[{order}].defaultValuesBySlot", "Defaults may only reference slots declared on the page.")
    return new_vocab_tags


def _page_item(story_template_id, theme_pack_id, language_code, page):
    defaults = {}
    slots_by_id = {slot["slotId"]: slot for slot in page.get("slots", [])}
    for slot_id, value in (page.get("defaultValuesBySlot") or {}).items():
        if value.get("type") == "asset":
            slot = slots_by_id[slot_id]
            asset_id = _resolve_asset_hint(
                theme_pack_id, slot["slotTag"], value.get("displayLabelHint"), language_code
            )
            if asset_id:
                defaults[slot_id] = {"type": "asset", "assetId": asset_id}
        elif value.get("type") == "text" and isinstance(value.get("value"), str):
            defaults[slot_id] = {"type": "text", "value": value["value"]}
        else:
            raise InputError(
                f"stage1Output.pages[{page['pageOrder']}].defaultValuesBySlot.{slot_id}",
                "Default must be a valid asset hint or text value.",
            )
    return {
        "storyTemplateId": story_template_id,
        "pageOrder": page["pageOrder"],
        "textTemplate": page["textTemplate"],
        "sceneDescription": page.get("sceneDescription", ""),
        "slots": page.get("slots", []),
        "baseLayers": [],
        "defaultValuesBySlot": defaults,
    }


def _resolve_asset_hint(theme_pack_id, slot_tag, hint, language_code):
    if not hint:
        return None
    result = assets_table.query(
        IndexName="byThemePack",
        KeyConditionExpression="themePackId = :tid",
        ExpressionAttributeValues={":tid": theme_pack_id},
    )
    for asset in result.get("Items", []):
        if asset.get("slotTag") == slot_tag and _display_label(asset, language_code) == hint:
            return asset["assetId"]
    return None
