import base64
import importlib.util
import json
import os
from io import BytesIO
from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
HANDLER_PATH = ROOT / "functions" / "story_production" / "handler.py"


def _table(client, name, partition_key, sort_key=None, gsi=None):
    attributes = [{"AttributeName": partition_key, "AttributeType": "S"}]
    key_schema = [{"AttributeName": partition_key, "KeyType": "HASH"}]
    if sort_key:
        attributes.append({"AttributeName": sort_key, "AttributeType": "S"})
        key_schema.append({"AttributeName": sort_key, "KeyType": "RANGE"})
    args = {
        "TableName": name,
        "AttributeDefinitions": attributes,
        "KeySchema": key_schema,
        "BillingMode": "PAY_PER_REQUEST",
    }
    if gsi:
        attributes.append({"AttributeName": gsi, "AttributeType": "S"})
        args["GlobalSecondaryIndexes"] = [{
            "IndexName": "byThemePack",
            "KeySchema": [{"AttributeName": gsi, "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        }]
    client.create_table(**args)


@pytest.fixture()
def production():
    mock = mock_aws()
    mock.start()
    os.environ.update({
        "AWS_DEFAULT_REGION": "us-east-1",
        "THEME_PACKS_TABLE": "packs",
        "ASSETS_TABLE": "assets",
        "STORY_TEMPLATES_TABLE": "templates",
        "STORY_TEMPLATE_PAGES_TABLE": "pages",
        "PRESET_CAST_MEMBERS_TABLE": "cast",
        "DEVELOPMENTAL_FRAMEWORKS_TABLE": "frameworks",
        "STORY_PRODUCTION_JOBS_TABLE": "jobs",
        "CATALOGUE_ASSETS_BUCKET": "catalogue-assets-test",
        "CDN_DOMAIN": "cdn.example.test",
        "BEDROCK_STYLE_GUIDE_MODEL_ARN": "arn:aws:bedrock:us-east-1:000000000000:inference-profile/us.stability.stable-image-style-guide-v1:0",
        "BEDROCK_REMOVE_BG_MODEL_ARN": "arn:aws:bedrock:us-east-1:000000000000:inference-profile/us.stability.stable-image-remove-background-v1:0",
    })
    client = boto3.client("dynamodb", region_name="us-east-1")
    _table(client, "packs", "themePackId")
    _table(client, "assets", "assetId", gsi="themePackId")
    _table(client, "templates", "storyTemplateId", gsi="themePackId")
    _table(client, "pages", "storyTemplateId", "pageOrder")
    _table(client, "cast", "castMemberId")
    _table(client, "frameworks", "frameworkId")
    _table(client, "jobs", "jobId")
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="catalogue-assets-test")

    db = boto3.resource("dynamodb", region_name="us-east-1")
    db.Table("packs").put_item(Item={
        "themePackId": "pack-1",
        "name": "Sleepy Forest",
        "description": "Quiet woodland",
        "developmentalFrameworks": ["curiosity"],
        "nameSuggestions": {
            "place_name": {"en": ["Mossy Hollow"], "es": ["Claro de Luna"]},
        },
        "catalogueStatus": "published",
    })
    db.Table("frameworks").put_item(Item={
        "frameworkId": "curiosity",
        "displayName": "Curiosity",
        "narrativeGuidance": "Follow something gentle and notice closely.",
        "creativeBriefQuestions": [
            {"questionId": "noticed", "prompt": "What is noticed?"},
        ],
        "catalogueStatus": "published",
    })
    db.Table("cast").put_item(Item={
        "castMemberId": "bear",
        "name": "Barnaby",
        "personalityDescription": "Gentle and curious",
        "availableThemePacks": ["pack-1"],
        "catalogueStatus": "published",
    })
    db.Table("assets").put_item(Item={
        "assetId": "fox-es",
        "themePackId": "pack-1",
        "slotTag": "sidekick_animal",
        "layerType": "prop_character",
        "displayLabel": {"en": "fox", "es": "zorro"},
        "reviewStatus": "published",
    })

    spec = importlib.util.spec_from_file_location("story_production_handler_test", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        yield module, db
    finally:
        mock.stop()


def test_prepare_returns_questions_and_context(production):
    handler, _ = production
    result = handler.lambda_handler({
        "action": "prepare",
        "themePackId": "pack-1",
        "frameworkId": "curiosity",
        "languageCode": "en",
    }, None)

    assert result["status"] == "ok"
    assert result["framework"]["creativeBriefQuestions"][0]["questionId"] == "noticed"
    assert result["castMembers"][0]["castMemberId"] == "bear"


def test_compose_rejects_page_count_below_contract_floor(production):
    handler, _ = production
    result = handler.lambda_handler({
        "action": "compose",
        "themePackId": "pack-1",
        "frameworkId": "curiosity",
        "languageCode": "en",
        "castMemberId": "bear",
        "minPageCount": 9,
    }, None)

    assert result == {
        "status": "refused",
        "field": "minPageCount",
        "reason": "minPageCount must be an integer of at least 10.",
    }


def test_compose_concepts_builds_manual_concept_studio_input(production):
    handler, _ = production
    result = handler.lambda_handler({
        "action": "compose_concepts",
        "themePackId": "pack-1",
        "frameworkId": "curiosity",
        "languageCode": "en",
        "castMemberId": "bear",
        "familyIntent": "A grandparent and child share the joy of noticing small things.",
        "creativeBriefAnswers": {"noticed": "A tiny light under a leaf."},
        "conceptCount": 4,
    }, None)

    concept_input = result["conceptInput"]
    assert result["mode"] == "manual"
    assert result["promptVersion"] == "stage0-concept-studio-v1"
    assert concept_input["CONCEPT_COUNT"] == 4
    assert concept_input["FAMILY_INTENT"].startswith("A grandparent")
    assert concept_input["PRODUCER_ANSWERS"] == [
        {"questionId": "noticed", "answer": "A tiny light under a leaf."}
    ]
    assert result["assembledPrompt"].startswith("You are the Concept Studio")
    assert "CONCEPT_INPUT_JSON\n{" in result["assembledPrompt"]
    assert '"CONCEPT_COUNT": 4' in result["assembledPrompt"]


def test_generate_concepts_invokes_bedrock_and_validates_output(production):
    handler, _ = production
    concept = {
        "workingTitle": "The Listening Leaf",
        "toddlerHook": "A leaf makes a tiny sound.",
        "emotionalPromise": "Listening together feels safe.",
        "centralSituation": "Barnaby follows the sound.",
        "resolution": "Friends are humming a bedtime song.",
        "repeatableElement": "Stop, look, listen.",
        "familyConnection": "The family repeats the sounds.",
        "personalizationMoments": ["favorite sound"],
        "bedtimeEnding": "The song becomes a hush.",
        "existingSlotTagsToReuse": ["sidekick_animal"],
        "newArtLikelyNeeded": [],
        "distinctnessRationale": "It is driven by listening rather than a walk with a friend.",
        "risks": [],
    }

    class Bedrock:
        def converse(self, **kwargs):
            assert kwargs["modelId"] == "us.anthropic.claude-sonnet-4-6"
            assert "CONCEPT_INPUT_JSON" in kwargs["messages"][0]["content"][0]["text"]
            return {"output": {"message": {"content": [{
                "text": json.dumps({"status": "ok", "concepts": [concept] * 3})
            }]}}}

    handler.bedrock_runtime = Bedrock()
    result = handler.lambda_handler({
        "action": "generate_concepts",
        "themePackId": "pack-1",
        "frameworkId": "curiosity",
        "languageCode": "en",
        "castMemberId": "bear",
        "familyIntent": "Share the joy of listening together.",
        "creativeBriefAnswers": {"noticed": "A tiny sound."},
        "conceptCount": 3,
    }, None)

    assert result["status"] == "ok"
    assert result["mode"] == "bedrock"
    assert result["modelId"] == "us.anthropic.claude-sonnet-4-6"
    assert len(result["concepts"]) == 3


def test_compose_preserves_selected_concept_as_stage1_brief(production):
    handler, _ = production
    result = handler.lambda_handler({
        "action": "compose",
        "themePackId": "pack-1",
        "frameworkId": "curiosity",
        "languageCode": "en",
        "castMemberId": "bear",
        "selectedConcept": {
            "workingTitle": "The Listening Leaf",
            "toddlerHook": "A leaf makes a new sound at every step.",
            "emotionalPromise": "Careful listening makes unfamiliar places feel safe.",
            "centralSituation": "Barnaby follows the sounds to find their source.",
            "resolution": "The sounds come from friends making a bedtime song.",
            "repeatableElement": "Step, stop, listen.",
            "familyConnection": "The family repeats each sound together.",
            "personalizationMoments": ["favorite sound"],
            "bedtimeEnding": "The final sound becomes a hush.",
        },
    }, None)

    brief = result["stage1Input"]["CREATIVE_BRIEF"]
    assert result["promptVersion"] == "stage1-story-slots-v1"
    assert result["stage1Input"]["WORKING_TITLE"] == "The Listening Leaf"
    assert "Working title: The Listening Leaf" in brief
    assert "Emotional promise: Careful listening" in brief
    assert "Personalization moments: favorite sound" in brief
    assert result["assembledPrompt"].startswith("You are the Story & Slot Generation Agent")
    assert "STAGE_1_INPUT_JSON\n{" in result["assembledPrompt"]
    assert '"WORKING_TITLE": "The Listening Leaf"' in result["assembledPrompt"]


def test_generate_story_invokes_bedrock_and_returns_reviewable_output(production):
    handler, _ = production
    pages = [{
        "pageOrder": f"{index:04d}",
        "textTemplate": f"Barnaby listens gently on page {index}.",
        "sceneDescription": "A quiet forest.",
        "slots": [],
        "defaultValuesBySlot": {},
    } for index in range(1, 11)]
    model_output = {
        "status": "ok",
        "storyTemplate": {
            "title": "The Listening Leaf",
            "oneLineSummary": "Barnaby follows a sound to a gentle bedtime song.",
            "developmentalFramework": "curiosity",
            "languageCode": "en",
            "isQuickStoryDefault": False,
        },
        "pages": pages,
        "newNameSuggestionsProposed": {},
        "newSlotTagsNeedingArt": [],
    }

    class Bedrock:
        def converse(self, **kwargs):
            system_prompt = kwargs["system"][0]["text"]
            assert "WRITING STYLE RULES" in system_prompt
            assert "Do not use em dashes (—) anywhere in the story." in system_prompt
            assert "professionally edited children's picture book" in system_prompt
            assert "STAGE_1_INPUT_JSON" in kwargs["messages"][0]["content"][0]["text"]
            return {"output": {"message": {"content": [{"text": json.dumps(model_output)}]}}}

    handler.bedrock_runtime = Bedrock()
    result = handler.lambda_handler({
        "action": "generate_story",
        "themePackId": "pack-1",
        "frameworkId": "curiosity",
        "languageCode": "en",
        "castMemberId": "bear",
        "selectedConcept": {
            "workingTitle": "The Listening Leaf",
            "toddlerHook": "A leaf makes a tiny sound.",
            "emotionalPromise": "Listening together feels safe.",
            "centralSituation": "Barnaby follows the sound.",
            "resolution": "Friends are humming a bedtime song.",
            "repeatableElement": "Stop, look, listen.",
            "familyConnection": "The family repeats the sounds.",
            "personalizationMoments": ["favorite sound"],
            "bedtimeEnding": "The song becomes a hush.",
        },
    }, None)

    assert result["status"] == "ok"
    assert result["mode"] == "bedrock"
    assert result["stage1Output"]["storyTemplate"]["title"] == "The Listening Leaf"
    assert len(result["stage1Output"]["pages"]) == 10


def test_compose_localizes_name_suggestions_and_keeps_slot_vocabulary_canonical(production):
    handler, _ = production
    result = handler.lambda_handler({
        "action": "compose",
        "themePackId": "pack-1",
        "frameworkId": "curiosity",
        "languageCode": "es",
        "castMemberId": "bear",
        "creativeBriefAnswers": {"noticed": "Un rastro de hojas brillantes."},
    }, None)

    stage1 = result["stage1Input"]
    assert stage1["EXISTING_NAME_SUGGESTIONS"] == [
        {"slotTag": "place_name", "suggestions": ["Claro de Luna"]}
    ]
    assert stage1["EXISTING_SLOT_VOCABULARY"][0]["sampleDisplayLabels"] == ["fox"]
    assert stage1["CREATIVE_BRIEF"] == "Un rastro de hojas brillantes."


def test_write_draft_persists_validated_template_and_pages(production):
    handler, db = production
    pages = [
        {
            "pageOrder": f"{index:04d}",
            "textTemplate": f"Barnaby notices something gentle on page {index}.",
            "sceneDescription": "A quiet forest clearing.",
            "slots": [],
            "defaultValuesBySlot": {},
        }
        for index in range(1, 11)
    ]
    result = handler.lambda_handler({
        "action": "write_draft",
        "themePackId": "pack-1",
        "frameworkId": "curiosity",
        "languageCode": "en",
        "castMemberId": "bear",
        "translationGroupId": "translation-1",
        "stage1Output": {
            "status": "ok",
            "storyTemplate": {
                "title": "The Gentle Trail",
                "oneLineSummary": "Barnaby follows a quiet trail and discovers a clearing.",
                "developmentalFramework": "curiosity",
                "languageCode": "en",
                "isQuickStoryDefault": False,
            },
            "pages": pages,
            "newNameSuggestionsProposed": {},
            "newSlotTagsNeedingArt": [],
        },
    }, None)

    assert result["status"] == "ok"
    assert result["pageCount"] == 10
    stored = db.Table("templates").get_item(
        Key={"storyTemplateId": result["storyTemplateId"]}
    )["Item"]
    assert stored["catalogueStatus"] == "draft"
    assert stored["castMemberId"] == "bear"
    assert stored["translationGroupId"] == "translation-1"
    written_pages = db.Table("pages").query(
        KeyConditionExpression="storyTemplateId = :tid",
        ExpressionAttributeValues={":tid": result["storyTemplateId"]},
    )["Items"]
    assert len(written_pages) == 10


# ===========================================================================
# Illustration pipeline: identity lineage, master/variant generation,
# procedural effects, house-style/character-bible locking, persistence.
# ===========================================================================

def _tiny_png_bytes(color):
    img = Image.new("RGBA", (4, 4), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _tiny_png_b64(color):
    return base64.b64encode(_tiny_png_bytes(color)).decode()


class _StreamingBody:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


# Fixed, distinct colors per model so tests can assert on exact byte content
# rather than just "some image was returned" -- e.g. proving a variant's
# reference was the master's own (remove-bg colored) output, not the raw
# style-guide output (which the house-style reference itself never goes
# past -- it's not remove-bg'd, see _ensure_house_style_reference).
_STYLE_GUIDE_COLOR = (10, 20, 30, 255)
_REMOVE_BG_COLOR = (40, 50, 60, 255)


class FakeImageBedrock:
    """Mock for handler.bedrock_runtime_images -- covers invoke_model for the
    style-guide/remove-background calls (including the house-style reference,
    which now goes through style-guide too) and records every call for
    assertions.
    """
    def __init__(self):
        self.calls = []

    def invoke_model(self, modelId, body, contentType, accept):
        payload = json.loads(body)
        self.calls.append({"modelId": modelId, "body": payload})
        if "remove-background" in modelId:
            color = _REMOVE_BG_COLOR
        else:  # style-guide -- both regular calls and the house-style reference
            color = _STYLE_GUIDE_COLOR
        response = {"images": [_tiny_png_b64(color)], "seeds": [1], "finish_reasons": [None]}
        return {"body": _StreamingBody(json.dumps(response).encode())}


class FakeLambdaClient:
    """Captures async self-invocations instead of actually invoking Lambda --
    tests replay each captured payload through handler.lambda_handler
    directly to exercise the worker deterministically.
    """
    def __init__(self):
        self.invocations = []

    def invoke(self, FunctionName, InvocationType, Payload):
        self.invocations.append(json.loads(Payload))


def _wire_fake_bedrock(handler):
    fake = FakeImageBedrock()
    handler.bedrock_runtime_images = fake
    fake_lambda = FakeLambdaClient()
    handler.lambda_client = fake_lambda
    handler.SELF_FUNCTION_NAME = "story-production-test"
    return fake, fake_lambda


def _minimal_character_bible(species="firefly"):
    return {
        "species": species,
        "approximateAge": "not applicable",
        "headShape": "small rounded oval",
        "earShape": "none",
        "muzzle": "none",
        "eyeConstruction": "two small round dots, centered",
        "bodyProportions": "one rounded oval body",
        "silhouette": "compact rounded oval",
        "clothing": "none",
        "accessories": "none",
        "outline": "warm dark outline, consistent width",
        "palette": ["#3B2F1E", "#FFE9A8"],
    }


def test_variant_without_a_known_identity_is_refused(production):
    """#1/#7 (validation half): a variant must reference a real identity --
    it cannot silently stand in for a new, undeclared character.
    """
    handler, _ = production
    output = {
        "status": "ok",
        "assets": [{
            "assetKind": "VARIANT_OF_IDENTITY",
            "identityKey": "no_such_identity",
            "variantKey": "sleepy",
            "layerType": "cast_expression",
            "mutation": {"pose": "lying down"},
            "forPageOrders": ["0001"],
            "depthGroup": "Foreground",
            "zIndexDefault": 10,
            "transform": {"center_x": 0, "center_y": 0, "width": 10, "height": 10, "rotation_degrees": 0},
        }],
    }
    with pytest.raises(handler.InputError):
        handler._validate_illustration_spec(output, "barnaby", cast_already_has_base=False)


def test_variant_may_reference_protagonist_when_cast_already_has_base(production):
    handler, _ = production
    output = {
        "status": "ok",
        "assets": [{
            "assetKind": "VARIANT_OF_IDENTITY",
            "identityKey": "barnaby",
            "variantKey": "sleepy",
            "layerType": "cast_expression",
            "mutation": {"pose": "lying down"},
            "forPageOrders": ["0001"],
            "depthGroup": "Foreground",
            "zIndexDefault": 10,
            "transform": {"center_x": 0, "center_y": 0, "width": 10, "height": 10, "rotation_degrees": 0},
        }],
    }
    assets = handler._validate_illustration_spec(output, "barnaby", cast_already_has_base=True)
    assert assets[0]["identityKey"] == "barnaby"


def test_story_scoped_sidekick_gets_master_and_shared_variant_lineage(production):
    """#2/#3/#4/#5/#6/#9/#10: a story-invented recurring companion gets one
    master identity; multiple variants derive from and reference that same
    master; the variant's provider reference is the master's own generated
    image (not the generic house-style reference); the locked house-style
    text and unchanged character-bible fields are both present in the
    compiled prompts; everything is actually persisted into Assets.
    """
    handler, db = production
    fake_bedrock, fake_lambda = _wire_fake_bedrock(handler)
    style_id = "cartoon"
    bible = _minimal_character_bible()

    assets = [
        {
            "assetKind": "NEW_IDENTITY", "identityKey": "sidekick_firefly", "kind": "STORY_CHARACTER",
            "layerType": "prop_character", "characterBible": bible,
            "masterPrompt": "wings spread flat and symmetric, facing forward, centered",
            "forPageOrders": [], "depthGroup": "Midground", "zIndexDefault": 15,
            "transform": {"center_x": 500, "center_y": 500, "width": 100, "height": 100, "rotation_degrees": 0},
        },
        {
            "assetKind": "VARIANT_OF_IDENTITY", "identityKey": "sidekick_firefly", "variantKey": "searching",
            "layerType": "prop_character", "mutation": {"pose": "wings mid-flap, tilted forward 15 degrees"},
            "forPageOrders": ["0003"], "depthGroup": "Midground", "zIndexDefault": 15,
            "transform": {"center_x": 400, "center_y": 400, "width": 90, "height": 90, "rotation_degrees": 0},
        },
        {
            "assetKind": "VARIANT_OF_IDENTITY", "identityKey": "sidekick_firefly", "variantKey": "resting",
            "layerType": "prop_character", "mutation": {"pose": "wings folded flat against body"},
            "forPageOrders": ["0011"], "depthGroup": "Midground", "zIndexDefault": 15,
            "transform": {"center_x": 420, "center_y": 420, "width": 90, "height": 90, "rotation_degrees": 0},
        },
    ]

    result = handler.lambda_handler({
        "action": "generate_illustrations",
        "themePackId": "pack-1", "styleId": style_id,
        "storyTemplateId": "story-1", "castMemberId": "bear",
        "assets": assets,
    }, None)

    assert result["status"] == "ok"
    assert len(result["masters"]) == 1
    master_asset_id = result["masters"][0]["assetId"]
    master_row = db.Table("assets").get_item(Key={"assetId": master_asset_id})["Item"]

    # #2: story-specific identity, scoped to the story (not the cast member
    # or theme pack), with its immutable character bible persisted.
    assert master_row["role"] == "MASTER_CHARACTER"
    assert master_row["scopeType"] == "STORY"
    assert master_row["scopeId"] == "story-1"
    assert master_row["characterBible"]["species"] == "firefly"

    # #5: the locked house-style block appears verbatim in the compiled
    # prompt -- not some LLM paraphrase of it.
    assert handler.compile_house_style_block(style_id) in master_row["compiledPrompt"]

    # Run both fanned-out variant jobs (the async self-invocations captured
    # instead of actually firing).
    assert len(fake_lambda.invocations) == 2
    for payload in fake_lambda.invocations:
        assert payload["masterAssetId"] == master_asset_id
        outcome = handler.lambda_handler(payload, None)
        assert outcome["status"] == "ok"

    searching_id = handler._deterministic_asset_id("STORY", "story-1", "sidekick_firefly", style_id, "searching")
    resting_id = handler._deterministic_asset_id("STORY", "story-1", "sidekick_firefly", style_id, "resting")
    searching_row = db.Table("assets").get_item(Key={"assetId": searching_id})["Item"]
    resting_row = db.Table("assets").get_item(Key={"assetId": resting_id})["Item"]

    # #3/#10: both variants reference the SAME master asset -- not two
    # independently generated fireflies.
    assert searching_row["masterAssetId"] == master_asset_id
    assert resting_row["masterAssetId"] == master_asset_id
    assert searching_row["role"] == "CHARACTER_VARIANT"

    # #6: the structured mutation is what's stored/compiled, not free prose
    # re-describing the character.
    assert searching_row["mutation"] == {"pose": "wings mid-flap, tilted forward 15 degrees"}
    assert "firefly" in searching_row["compiledPrompt"]
    assert "small rounded oval" in searching_row["compiledPrompt"]  # bible's headShape, unchanged

    # #4: the variant's Style Guide call used the MASTER's own (remove-bg'd)
    # generated image as the reference -- never the raw house-style reference.
    house_style_ref_b64 = _tiny_png_b64(_STYLE_GUIDE_COLOR)
    style_guide_calls = [c for c in fake_bedrock.calls if "style-guide" in c["modelId"]]
    variant_style_guide_calls = [c for c in style_guide_calls if c["body"].get("fidelity") == handler.VARIANT_FIDELITY]
    assert len(variant_style_guide_calls) == 2
    master_final_image_b64 = _tiny_png_b64(_REMOVE_BG_COLOR)  # every asset goes through remove-bg except backgrounds
    for call in variant_style_guide_calls:
        assert call["body"]["image"] == master_final_image_b64
        assert call["body"]["image"] != house_style_ref_b64


def test_repeated_generation_reuses_master_without_recalling_bedrock(production):
    """#11: retrying generation for an unchanged identity must not create a
    second, unrelated master -- the canonical asset is reused.
    """
    handler, db = production
    fake_bedrock, _ = _wire_fake_bedrock(handler)
    style_id = "cartoon"
    bible = _minimal_character_bible(species="rabbit")
    house_style_ref_b64, house_style_fp = handler._ensure_house_style_reference(
        "pack-1", style_id
    )
    calls_after_setup = len(fake_bedrock.calls)

    first = handler._ensure_master_character(
        "STORY", "story-1", "sidekick_rabbit", style_id, "prop_character",
        bible, "sitting upright, facing forward", house_style_ref_b64, house_style_fp,
        force_regenerate=False,
    )
    calls_after_first = len(fake_bedrock.calls)
    assert calls_after_first > calls_after_setup

    second = handler._ensure_master_character(
        "STORY", "story-1", "sidekick_rabbit", style_id, "prop_character",
        bible, "sitting upright, facing forward", house_style_ref_b64, house_style_fp,
        force_regenerate=False,
    )
    assert len(fake_bedrock.calls) == calls_after_first  # no new Bedrock calls at all
    assert second["assetId"] == first["assetId"]
    assert second["generationRevision"] == first["generationRevision"] == 1

    third = handler._ensure_master_character(
        "STORY", "story-1", "sidekick_rabbit", style_id, "prop_character",
        bible, "sitting upright, facing forward", house_style_ref_b64, house_style_fp,
        force_regenerate=True,
    )
    assert len(fake_bedrock.calls) > calls_after_first  # force_regenerate does call Bedrock again
    assert third["assetId"] == first["assetId"]  # same canonical identity
    assert third["generationRevision"] == 2  # but a new revision


def test_generated_assets_auto_publish(production):
    """The generative pipeline has no separate human-review step (unlike the
    older hand-curated assets seeded by backend/scripts/seed_story_content.py) --
    every generated asset must come back reviewStatus: "published" immediately,
    or read paths that filter on it (_cast_base_layers, slot options) would
    never surface real generated art at all."""
    handler, db = production
    _wire_fake_bedrock(handler)
    style_id = "cartoon"
    bible = _minimal_character_bible(species="owl")
    house_style_ref_b64, house_style_fp = handler._ensure_house_style_reference("pack-1", style_id)

    result = handler._ensure_master_character(
        "STORY", "story-1", "sidekick_owl", style_id, "prop_character",
        bible, "perched upright, facing forward", house_style_ref_b64, house_style_fp,
        force_regenerate=False,
    )
    assert result["reviewStatus"] == "published"
    stored = db.Table("assets").get_item(Key={"assetId": result["assetId"]})["Item"]
    assert stored["reviewStatus"] == "published"


def test_procedural_glow_never_calls_bedrock(production):
    """#8: a light/glow effect renders deterministically -- it must not
    reach an image-generation provider at all.
    """
    handler, db = production
    fake_bedrock, _ = _wire_fake_bedrock(handler)
    result = handler._ensure_procedural_effect(
        "STORY", "story-1", "glow_gold", "cartoon", "radial_glow", "golden", 120, 2.0, 0.85,
        force_regenerate=False,
    )
    assert fake_bedrock.calls == []
    assert result["role"] == "PROCEDURAL_EFFECT"
    assert result["provider"] == "procedural"
    assert result["generationType"] == "PROCEDURAL"
    stored = db.Table("assets").get_item(Key={"assetId": result["assetId"]})["Item"]
    assert stored["cdnKey"] == result["cdnKey"]


def test_background_prompt_carries_scene_constraints(production):
    """#9: background prompts are compiled from concrete scene geometry,
    with the standard no-filler negative-space instructions present --
    not free "magical/whimsical" prose.
    """
    handler, db = production
    _wire_fake_bedrock(handler)
    style_id = "cartoon"
    house_style_ref_b64, house_style_fp = handler._ensure_house_style_reference(
        "pack-1", style_id
    )
    scene = {
        "groundShape": "single flat ground band across the bottom third",
        "treeMasses": "2 tree masses, one at each side edge",
        "skyType": "flat dusk gradient, orange near horizon to deep indigo at top",
        "starCount": "6 simple star shapes, upper third",
        "horizonLine": "straight, at the lower third boundary",
        "otherElements": "none",
        "negativeSpaceNote": "central clearing kept empty",
    }
    result = handler._ensure_background(
        "STORY", "story-1", "woodland_dusk", style_id, scene,
        house_style_ref_b64, house_style_fp, force_regenerate=False,
    )
    prompt = result["compiledPrompt"]
    assert "Do not add visual interest merely to fill empty space." in prompt
    assert "central clearing kept empty" in prompt
    assert "2 tree masses, one at each side edge" in prompt
    assert result["role"] == "BACKGROUND"
    stored = db.Table("assets").get_item(Key={"assetId": result["assetId"]})["Item"]
    assert stored["layerType"] == "background"


# ===========================================================================
# write_illustrations: populating story_template_pages.baseLayers from a
# reviewed, already-generated Stage 2 plan.
# ===========================================================================

def _sidekick_assets():
    bible = _minimal_character_bible()
    return [
        {
            "assetKind": "NEW_IDENTITY", "identityKey": "sidekick_firefly", "kind": "STORY_CHARACTER",
            "layerType": "prop_character", "characterBible": bible,
            "masterPrompt": "wings spread flat and symmetric, facing forward, centered",
            "forPageOrders": [], "depthGroup": "Midground", "zIndexDefault": 15,
            "transform": {"center_x": 500, "center_y": 500, "width": 100, "height": 100, "rotation_degrees": 0},
        },
        {
            "assetKind": "VARIANT_OF_IDENTITY", "identityKey": "sidekick_firefly", "variantKey": "searching",
            "layerType": "prop_character", "mutation": {"pose": "wings mid-flap, tilted forward 15 degrees"},
            "forPageOrders": ["0003"], "depthGroup": "Midground", "zIndexDefault": 15,
            "transform": {"center_x": 400, "center_y": 400, "width": 90, "height": 90, "rotation_degrees": 0},
        },
        {
            "assetKind": "VARIANT_OF_IDENTITY", "identityKey": "sidekick_firefly", "variantKey": "resting",
            "layerType": "prop_character", "mutation": {"pose": "wings folded flat against body"},
            "forPageOrders": ["0011"], "depthGroup": "Midground", "zIndexDefault": 15,
            "transform": {"center_x": 420, "center_y": 420, "width": 90, "height": 90, "rotation_degrees": 0},
        },
    ]


def _put_pages(db, story_template_id, page_orders):
    for page_order in page_orders:
        db.Table("pages").put_item(Item={
            "storyTemplateId": story_template_id, "pageOrder": page_order,
            "textTemplate": f"Page {page_order}.", "slots": [], "baseLayers": [],
        })


def test_write_illustrations_populates_page_base_layers(production):
    handler, db = production
    fake_bedrock, fake_lambda = _wire_fake_bedrock(handler)
    style_id = "cartoon"
    assets = _sidekick_assets()
    _put_pages(db, "story-1", ["0003", "0011", "0099"])

    generated = handler.lambda_handler({
        "action": "generate_illustrations",
        "themePackId": "pack-1", "styleId": style_id,
        "storyTemplateId": "story-1", "castMemberId": "bear",
        "assets": assets,
    }, None)
    assert generated["status"] == "ok"
    for payload in fake_lambda.invocations:
        outcome = handler.lambda_handler(payload, None)
        assert outcome["status"] == "ok"

    result = handler.lambda_handler({
        "action": "write_illustrations",
        "themePackId": "pack-1", "styleId": style_id,
        "storyTemplateId": "story-1", "castMemberId": "bear",
        "assets": assets,
    }, None)
    assert result["status"] == "ok"
    assert sorted(result["pagesUpdated"]) == ["0003", "0011"]
    assert result["layerCount"] == 2

    searching_id = handler._deterministic_asset_id("STORY", "story-1", "sidekick_firefly", style_id, "searching")
    page_0003 = db.Table("pages").get_item(Key={"storyTemplateId": "story-1", "pageOrder": "0003"})["Item"]
    assert len(page_0003["baseLayers"]) == 1
    layer = page_0003["baseLayers"][0]
    assert layer["assetId"] == searching_id
    assert layer["layerType"] == "prop_character"
    assert layer["identityKey"] == "sidekick_firefly"
    assert layer["cdnKey"]

    resting_id = handler._deterministic_asset_id("STORY", "story-1", "sidekick_firefly", style_id, "resting")
    page_0011 = db.Table("pages").get_item(Key={"storyTemplateId": "story-1", "pageOrder": "0011"})["Item"]
    assert page_0011["baseLayers"][0]["assetId"] == resting_id

    # Untouched page keeps its existing (empty) baseLayers.
    page_0099 = db.Table("pages").get_item(Key={"storyTemplateId": "story-1", "pageOrder": "0099"})["Item"]
    assert page_0099["baseLayers"] == []


def test_write_illustrations_rejects_when_asset_not_yet_generated(production):
    """The async variant jobs from generate_illustrations were never run --
    write_illustrations must refuse rather than writing a page layer with no
    real image behind it."""
    handler, db = production
    _wire_fake_bedrock(handler)
    style_id = "cartoon"
    assets = _sidekick_assets()
    _put_pages(db, "story-1", ["0003", "0011"])

    handler.lambda_handler({
        "action": "generate_illustrations",
        "themePackId": "pack-1", "styleId": style_id,
        "storyTemplateId": "story-1", "castMemberId": "bear",
        "assets": assets,
    }, None)  # fanned-out jobs deliberately not run

    result = handler.lambda_handler({
        "action": "write_illustrations",
        "themePackId": "pack-1", "styleId": style_id,
        "storyTemplateId": "story-1", "castMemberId": "bear",
        "assets": assets,
    }, None)
    assert result["status"] == "refused"
    assert result["field"] == "assets"


def test_write_illustrations_rejects_unknown_page_order(production):
    """A Stage 2 plan naming a pageOrder that was never written by
    write_draft is a data-integrity bug, not something to silently drop."""
    handler, db = production
    fake_bedrock, fake_lambda = _wire_fake_bedrock(handler)
    style_id = "cartoon"
    assets = _sidekick_assets()
    _put_pages(db, "story-1", ["0003"])  # "0011" deliberately missing

    handler.lambda_handler({
        "action": "generate_illustrations",
        "themePackId": "pack-1", "styleId": style_id,
        "storyTemplateId": "story-1", "castMemberId": "bear",
        "assets": assets,
    }, None)
    for payload in fake_lambda.invocations:
        handler.lambda_handler(payload, None)

    result = handler.lambda_handler({
        "action": "write_illustrations",
        "themePackId": "pack-1", "styleId": style_id,
        "storyTemplateId": "story-1", "castMemberId": "bear",
        "assets": assets,
    }, None)
    assert result["status"] == "refused"
    assert "0011" in result["reason"]


# ===========================================================================
# generate_one_illustration: single-asset generation, no job fan-out.
# ===========================================================================

def test_generate_one_illustration_generates_a_single_asset(production):
    """A producer should be able to validate one prompt's rendering without
    paying for (or fanning jobs out for) the rest of the plan."""
    handler, db = production
    _wire_fake_bedrock(handler)
    style_id = "cartoon"
    bible = _minimal_character_bible()
    asset = {
        "assetKind": "NEW_IDENTITY", "identityKey": "sidekick_firefly", "kind": "STORY_CHARACTER",
        "layerType": "prop_character", "characterBible": bible,
        "masterPrompt": "wings spread flat and symmetric, facing forward, centered",
        "forPageOrders": [], "depthGroup": "Midground", "zIndexDefault": 15,
        "transform": {"center_x": 500, "center_y": 500, "width": 100, "height": 100, "rotation_degrees": 0},
    }

    result = handler.lambda_handler({
        "action": "generate_one_illustration",
        "themePackId": "pack-1", "styleId": style_id,
        "storyTemplateId": "story-1", "castMemberId": "bear",
        "asset": asset,
    }, None)

    assert result["status"] == "ok"
    assert result["identityKey"] == "sidekick_firefly"
    assert result["cdnUrl"]
    stored = db.Table("assets").get_item(Key={"assetId": result["assetId"]})["Item"]
    assert stored["role"] == "MASTER_CHARACTER"
    assert stored["scopeType"] == "STORY"


def test_generate_one_illustration_variant_requires_existing_master(production):
    handler, _ = production
    _wire_fake_bedrock(handler)
    style_id = "cartoon"
    variant = {
        "assetKind": "VARIANT_OF_IDENTITY", "identityKey": "sidekick_firefly", "variantKey": "searching",
        "layerType": "prop_character", "mutation": {"pose": "wings mid-flap"},
        "forPageOrders": ["0003"], "depthGroup": "Midground", "zIndexDefault": 15,
        "transform": {"center_x": 400, "center_y": 400, "width": 90, "height": 90, "rotation_degrees": 0},
    }

    result = handler.lambda_handler({
        "action": "generate_one_illustration",
        "themePackId": "pack-1", "styleId": style_id,
        "storyTemplateId": "story-1", "castMemberId": "bear",
        "asset": variant,
    }, None)
    assert result["status"] == "refused"
    assert "sidekick_firefly" in result["reason"]


def test_house_style_reference_generated_via_style_guide_not_text_to_image(production):
    """The house-style reference used to be a separate stable-image-core
    text-to-image call -- confirmed live, that reliably produced a full
    illustrated scene with a human figure instead of an isolated subject.
    It must now go through the same Style Guide model as everything else,
    seeded with a blank image, at HOUSE_STYLE_REFERENCE_FIDELITY."""
    handler, _ = production
    fake_bedrock, _ = _wire_fake_bedrock(handler)
    handler._ensure_house_style_reference("pack-1", "cartoon")

    style_guide_calls = [c for c in fake_bedrock.calls if "style-guide" in c["modelId"]]
    assert len(style_guide_calls) == 1
    assert style_guide_calls[0]["body"]["fidelity"] == handler.HOUSE_STYLE_REFERENCE_FIDELITY
    assert "image" in style_guide_calls[0]["body"]


def test_house_style_reference_force_regenerate_bypasses_cache(production):
    """The reference is a generative, not-perfectly-deterministic call (see
    compile_house_style_reference_prompt) -- force_regenerate lets a
    producer retry a bad roll without needing a full HOUSE_STYLE_VERSION
    bump, which would also invalidate every already-generated asset in
    that style across every theme pack."""
    handler, _ = production
    fake_bedrock, _ = _wire_fake_bedrock(handler)
    handler._ensure_house_style_reference("pack-1", "cartoon")
    calls_after_first = len(fake_bedrock.calls)

    handler._ensure_house_style_reference("pack-1", "cartoon")
    assert len(fake_bedrock.calls) == calls_after_first  # cache hit, no new call

    handler._ensure_house_style_reference("pack-1", "cartoon", force_regenerate=True)
    assert len(fake_bedrock.calls) > calls_after_first  # forced past the cache


def test_regenerate_house_style_reference_action(production):
    handler, _ = production
    fake_bedrock, _ = _wire_fake_bedrock(handler)
    handler.lambda_handler({
        "action": "regenerate_house_style_reference",
        "themePackId": "pack-1", "styleId": "cartoon",
    }, None)
    calls_after_first = len(fake_bedrock.calls)
    assert calls_after_first > 0

    result = handler.lambda_handler({
        "action": "regenerate_house_style_reference",
        "themePackId": "pack-1", "styleId": "cartoon",
    }, None)
    assert result["status"] == "ok"
    assert result["cdnUrl"]
    assert len(fake_bedrock.calls) > calls_after_first  # bypassed the cache again


# ===========================================================================
# Job-queue robustness: a deterministic validator refusal is expected,
# recoverable input, not a system fault -- confirmed live, generate_story
# was surfacing every refusal (slotId drift, dash violations, etc.) as a
# "failed" job with a raw exception string and a full traceback in the
# logs, indistinguishable from a genuine crash.
# ===========================================================================

def test_sanitize_dashes_replaces_em_and_en_dashes(production):
    handler, _ = production
    assert handler._sanitize_dashes("The forest was quiet — and then a sound.") == \
        "The forest was quiet, and then a sound."
    assert handler._sanitize_dashes("the color–the golden one–was rare.") == \
        "the color, the golden one, was rare."
    assert handler._sanitize_dashes("no dashes here.") == "no dashes here."
    assert handler._sanitize_dashes(None) is None


def test_run_job_treats_input_error_as_refused_not_failed(production):
    handler, db = production
    result = handler.lambda_handler({
        "_jobId": "job-1",
        "action": "write_draft",
        # themePackId deliberately omitted -- _required_string raises
        # InputError immediately, no Bedrock call needed to exercise this.
    }, None)
    assert result["status"] == "refused"
    assert result["field"] == "themePackId"

    stored = db.Table("jobs").get_item(Key={"jobId": "job-1"})["Item"]
    assert stored["status"] == "completed"  # not "failed" -- this isn't a crash
    assert stored["result"]["status"] == "refused"
    assert stored["result"]["field"] == "themePackId"
    assert "errorMessage" not in stored
