"""Internal Tier 2 story-production orchestration.

Direct Lambda invocation only; this function is deliberately not exposed via
API Gateway. It composes the Stage 1 prompt input for manual use today and can
persist a reviewed Stage 1 response as draft catalogue rows. Bedrock invocation
is intentionally absent until model and review-boundary decisions are made.
"""

import json
import os
import re
import uuid
from pathlib import Path

import boto3


dynamodb = boto3.resource("dynamodb")
bedrock_runtime = boto3.client("bedrock-runtime")
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
      write_draft Validate reviewed Stage 1 JSON and write draft catalogue rows.
    """
    if (event or {}).get("_jobId"):
        return _run_job(event)
    try:
        return _dispatch(event or {})
    except InputError as error:
        return {"status": "refused", "field": error.field, "reason": str(error)}


def _dispatch(event):
        action = event.get("action")
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
        if action == "write_draft":
            return _write_draft(event)
        raise InputError(
            "action",
            "action must be 'prepare', 'compose_concepts', 'generate_concepts', "
            "'compose', 'generate_story', or 'write_draft'.",
        )


def _run_job(event):
    job_id = event.pop("_jobId")
    try:
        result = _dispatch(event)
        jobs_table.update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET #s = :s, #r = :r",
            ExpressionAttributeNames={"#s": "status", "#r": "result"},
            ExpressionAttributeValues={":s": "completed", ":r": result},
        )
    except Exception as error:
        jobs_table.update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET #s = :s, errorMessage = :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "failed", ":e": str(error)},
        )
        raise
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
            STAGE_1_PROMPT_PATH, "STAGE_1_INPUT_JSON", stage1_input
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
    output = _invoke_bedrock_json(
        STAGE_1_PROMPT_PATH,
        "STAGE_1_INPUT_JSON",
        composed["stage1Input"],
        max_tokens=16000,
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


def _assemble_prompt(prompt_path, input_label, prompt_input):
    try:
        instructions = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"Runtime prompt could not be loaded: {prompt_path.name}") from error
    return (
        f"{instructions}\n\n"
        f"{input_label}\n"
        f"{json.dumps(prompt_input, ensure_ascii=False, indent=2)}"
    )


def _invoke_bedrock_json(prompt_path, input_label, prompt_input, max_tokens):
    try:
        instructions = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"Runtime prompt could not be loaded: {prompt_path.name}") from error
    response = bedrock_runtime.converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": instructions}],
        messages=[{
            "role": "user",
            "content": [{
                "text": f"{input_label}\n{json.dumps(prompt_input, ensure_ascii=False)}"
            }],
        }],
        inferenceConfig={
            "maxTokens": max_tokens,
            "temperature": 0.7,
        },
    )
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict)).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise InputError("modelOutput", "Bedrock returned invalid JSON.") from error
    if not isinstance(result, dict):
        raise InputError("modelOutput", "Bedrock output must be a JSON object.")
    return result


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
    _validate_output(template, pages, framework["frameworkId"], language_code, minimum)

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
            value = ", ".join(str(item) for item in value)
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


def _validate_output(template, pages, framework_id, language_code, minimum):
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
    for page in pages:
        _validate_page(page)


def _validate_page(page):
    order = page["pageOrder"]
    text = page.get("textTemplate")
    if not isinstance(text, str) or not text.strip():
        raise InputError(f"stage1Output.pages[{order}].textTemplate", "textTemplate must be non-empty.")
    slots = page.get("slots") or []
    if not isinstance(slots, list):
        raise InputError(f"stage1Output.pages[{order}].slots", "slots must be an array.")
    slot_ids = set()
    for slot in slots:
        slot_id = slot.get("slotId") if isinstance(slot, dict) else None
        if not slot_id or slot_id in slot_ids:
            raise InputError(f"stage1Output.pages[{order}].slots", "Every slotId must be non-empty and unique on its page.")
        slot_ids.add(slot_id)
        if slot.get("slotType") not in VALID_SLOT_TYPES:
            raise InputError(f"stage1Output.pages[{order}].slots.{slot_id}", "Unsupported slotType.")
        if not slot.get("slotTag"):
            raise InputError(f"stage1Output.pages[{order}].slots.{slot_id}", "slotTag is required.")
        if f"{{{{{slot_id}}}}}" not in text:
            raise InputError(f"stage1Output.pages[{order}].textTemplate", f"Missing placeholder for slotId '{slot_id}'.")
    defaults = page.get("defaultValuesBySlot") or {}
    if not isinstance(defaults, dict) or any(key not in slot_ids for key in defaults):
        raise InputError(f"stage1Output.pages[{order}].defaultValuesBySlot", "Defaults may only reference slots declared on the page.")


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
