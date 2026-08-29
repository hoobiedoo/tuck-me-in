import importlib.util
import json
import os
from pathlib import Path

import boto3
import pytest
from moto import mock_aws


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
    })
    client = boto3.client("dynamodb", region_name="us-east-1")
    _table(client, "packs", "themePackId")
    _table(client, "assets", "assetId", gsi="themePackId")
    _table(client, "templates", "storyTemplateId", gsi="themePackId")
    _table(client, "pages", "storyTemplateId", "pageOrder")
    _table(client, "cast", "castMemberId")
    _table(client, "frameworks", "frameworkId")

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
