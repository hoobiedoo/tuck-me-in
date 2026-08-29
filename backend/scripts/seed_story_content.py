"""Seeds one complete, minimal ThemePack ("Sleepy Forest") so the Mad Libs
wizard's plumbing — Phase 1 browsing through publish — is exercisable
end-to-end against a real deployment. The art is the placeholder set from
generate_seed_placeholders.py, not production content; Tier 2 authoring
(real art, more packs, more templates) is a separate workstream. Safe to
run more than once — every write here is an idempotent put_item/upload.

Usage (after `cdk deploy`):
    pip install -r requirements-seed.txt
    python generate_seed_placeholders.py
    CATALOGUE_ASSETS_BUCKET=<bucket-name-from-cdk-output> python seed_story_content.py

Table names are the literal `table_name=` values from
backend/constructs/database.py — fixed strings, not CDK-generated, so no
CloudFormation lookup is needed for those. The S3 bucket name *is*
CDK-generated (see CatalogueAssetsBucketName in the deploy output) and
must be passed in.
"""

import os
import sys

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
CATALOGUE_ASSETS_BUCKET = os.environ.get("CATALOGUE_ASSETS_BUCKET")
# CloudFront only routes "book-assets/*" to the catalogue assets bucket
# (see storage.py's additional_behaviors) — nest under it rather than
# adding a second CloudFront behavior for one seed script.
ASSET_PREFIX = "book-assets/story-assets/placeholders"
SEED_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "seed_assets")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)

theme_packs_table = dynamodb.Table("tuck-me-in-theme-packs")
assets_table = dynamodb.Table("tuck-me-in-assets")
story_templates_table = dynamodb.Table("tuck-me-in-story-templates")
story_template_pages_table = dynamodb.Table("tuck-me-in-story-template-pages")
preset_cast_members_table = dynamodb.Table("tuck-me-in-preset-cast-members")
developmental_frameworks_table = dynamodb.Table("tuck-me-in-developmental-frameworks")

PACK_ID = "pack-sleepy-forest"
STYLE_ID = "cartoon"
FRAMEWORK = "exploration_curiosity"
CAST_ID = "cast-barnaby-bear"
TEMPLATE_ID = "template-sleepy-forest-quick"


def cdn_key(filename):
    return f"{ASSET_PREFIX}/{filename}"


def upload_placeholders():
    if not CATALOGUE_ASSETS_BUCKET:
        print("CATALOGUE_ASSETS_BUCKET not set — skipping image upload (DynamoDB rows will still seed).")
        return
    if not os.path.isdir(SEED_ASSETS_DIR):
        print(f"No {SEED_ASSETS_DIR} found — run generate_seed_placeholders.py first.")
        return
    for filename in os.listdir(SEED_ASSETS_DIR):
        key = cdn_key(filename)
        s3.upload_file(
            os.path.join(SEED_ASSETS_DIR, filename), CATALOGUE_ASSETS_BUCKET, key,
            ExtraArgs={"ContentType": "image/png"},
        )
        print(f"  uploaded {key}")


def seed_theme_pack():
    theme_packs_table.put_item(Item={
        "themePackId": PACK_ID,
        "name": "Sleepy Forest",
        "description": "A gentle woodland wind-down adventure.",
        "coverImageKey": cdn_key("pack-sleepy-forest-cover.png"),
        "styles": [STYLE_ID],
        "developmentalFrameworks": [FRAMEWORK],
        "catalogueStatus": "published",
        "tierRequired": "free",
        "nameSuggestions": {
            "sidekick_name": {"en": ["Pip", "Clover", "Acorn"]},
            "place_name": {"en": ["Mossy Hollow", "Whispering Grove", "Starlight Clearing"]},
        },
    })


def seed_developmental_frameworks():
    """Seeds all three known frameworks, not just the one this ThemePack
    uses — this table is the single source of truth referenced by both
    prompt docs (docs/tier2-ai-assisted-production-prompts.md's
    Developmental Framework Reference) and the mobile app's picker, so it
    should exist independent of any one pack."""
    frameworks = [
        {
            "frameworkId": "reassurance_separation",
            "displayName": "Reassurance & Separation",
            "parentFacingDescription": "For moments apart from someone or something familiar, always ending in a safe return.",
            "narrativeGuidance": (
                "Brief separation from someone/something familiar; the arc is entirely the "
                "safe, certain return. Never end on the \"apart\" state."
            ),
            "creativeBriefQuestions": [
                {"questionId": "separated_from", "prompt": "What is [cast] briefly apart from — a person, a place, a favorite thing?"},
                {"questionId": "safe_return", "prompt": "What does the safe, certain return actually look like?"},
            ],
            "catalogueStatus": "published",
        },
        {
            "frameworkId": "big_feelings_comfort",
            "displayName": "Big Feelings & Comfort",
            "parentFacingDescription": "For working through an ordinary strong feeling, gently and without rushing.",
            "narrativeGuidance": (
                "An ordinary strong feeling, named and sat with briefly, then a small concrete "
                "way through it. Don't rush past the feeling to fix it in one line."
            ),
            "creativeBriefQuestions": [
                {"questionId": "the_feeling", "prompt": "What's the specific feeling this one sits with? (frustrated, left out, overwhelmed, jealous, disappointed...)"},
                {"questionId": "way_through", "prompt": "What's the small, concrete way through it?"},
            ],
            "catalogueStatus": "published",
        },
        {
            "frameworkId": "exploration_curiosity",
            "displayName": "Exploration & Curiosity",
            "parentFacingDescription": "For noticing something new and following it somewhere gentle.",
            "narrativeGuidance": (
                "Noticing something new, following it somewhere gentle. Rewards looking closer, "
                "not winning or achieving."
            ),
            "creativeBriefQuestions": [
                {"questionId": "what_noticed", "prompt": "What does [cast] notice that pulls their curiosity?"},
                {"questionId": "where_it_leads", "prompt": "Where does following it lead?"},
            ],
            "catalogueStatus": "published",
        },
    ]
    for framework in frameworks:
        developmental_frameworks_table.put_item(Item=framework)


def seed_preset_cast():
    preset_cast_members_table.put_item(Item={
        "castMemberId": CAST_ID,
        "name": "Barnaby the Bear",
        "availableStyles": [STYLE_ID],
        "availableThemePacks": [PACK_ID],
        "catalogueStatus": "published",
    })

    assets_table.put_item(Item={
        "assetId": "asset-barnaby-body",
        "castMemberId": CAST_ID,
        "castMemberStyleKey": f"{CAST_ID}#{STYLE_ID}",
        "styleId": STYLE_ID,
        "layerType": "cast_base",
        "depthGroup": "Midground",
        "zIndexDefault": 20,
        "transform": {"center_x": 1024, "center_y": 950, "width": 500, "height": 500, "rotation_degrees": 0},
        "cdnKey": cdn_key("barnaby-body.png"),
        "reviewStatus": "published",
    })

    for expression in ("happy", "sleepy", "curious", "surprised"):
        assets_table.put_item(Item={
            "assetId": f"asset-expr-{expression}",
            "themePackId": PACK_ID,
            "styleId": STYLE_ID,
            "layerType": "cast_expression",
            "slotTag": "protagonist_expression",
            "packStyleSlotKey": f"{PACK_ID}#{STYLE_ID}#protagonist_expression",
            "castMemberId": CAST_ID,
            "expressionKey": expression,
            "displayLabel": {"en": expression},
            "depthGroup": "Midground",
            "zIndexDefault": 30,
            "transform": {"center_x": 1024, "center_y": 850, "width": 220, "height": 220, "rotation_degrees": 0},
            "cdnKey": cdn_key(f"expr-{expression}.png"),
            "isQuickStoryDefault": expression == "happy",
            "reviewStatus": "published",
        })


def seed_controlled_vocab_assets():
    animals = [("fox", "#D9772E"), ("rabbit", "#C9C2B4"), ("owl", "#8E6F4E")]
    for name, _ in animals:
        assets_table.put_item(Item={
            "assetId": f"asset-{name}",
            "themePackId": PACK_ID,
            "styleId": STYLE_ID,
            "layerType": "prop_character",
            "slotTag": "sidekick_animal",
            "packStyleSlotKey": f"{PACK_ID}#{STYLE_ID}#sidekick_animal",
            "displayLabel": {"en": name},
            "depthGroup": "Midground",
            "zIndexDefault": 15,
            "transform": {"center_x": 1500, "center_y": 1000, "width": 320, "height": 320, "rotation_degrees": 0},
            "cdnKey": cdn_key(f"{name}.png"),
            "isQuickStoryDefault": name == "fox",
            "reviewStatus": "published",
        })

    colors = ["golden", "silver", "violet"]
    for name in colors:
        assets_table.put_item(Item={
            "assetId": f"asset-color-{name}",
            "themePackId": PACK_ID,
            "styleId": STYLE_ID,
            "layerType": "prop_light",
            "slotTag": "descriptive_color",
            "packStyleSlotKey": f"{PACK_ID}#{STYLE_ID}#descriptive_color",
            "displayLabel": {"en": name},
            "depthGroup": "Background",
            "zIndexDefault": 5,
            "transform": {"center_x": 1700, "center_y": 300, "width": 260, "height": 260, "rotation_degrees": 0},
            "cdnKey": cdn_key(f"color-{name}.png"),
            "isQuickStoryDefault": name == "golden",
            "reviewStatus": "published",
        })


def seed_story_template():
    story_templates_table.put_item(Item={
        "storyTemplateId": TEMPLATE_ID,
        "translationGroupId": "translation-sleepy-forest-quick",
        "themePackId": PACK_ID,
        "castMemberId": CAST_ID,
        "developmentalFramework": FRAMEWORK,
        "languageCode": "en",
        "title": "A Walk in Sleepy Forest",
        "oneLineSummary": "Barnaby wakes up curious, meets a sidekick animal on the forest path, and settles in for a nap with his new friend.",
        "isQuickStoryDefault": True,
        "catalogueStatus": "published",
    })

    background_layer = {
        "assetId": "asset-bg-forest",
        "cdnKey": cdn_key("bg-forest.png"),
        "depthGroup": "Background",
        "zIndex": 0,
        "transform": {"center_x": 1024, "center_y": 768, "width": 2048, "height": 1536, "rotation_degrees": 0},
    }

    pages = [
        {
            "pageOrder": "0001",
            "textTemplate": "Barnaby the bear woke up feeling curious. He decided to explore {{place_name_slot}}.",
            "baseLayers": [background_layer],
            "slots": [
                {"slotId": "place_name_slot", "slotType": "CONTROLLED_VOCAB_WITH_OVERRIDE", "slotTag": "place_name", "required": True},
            ],
            "defaultValuesBySlot": {
                "place_name_slot": {"type": "text", "value": "Mossy Hollow"},
            },
        },
        {
            "pageOrder": "0002",
            "textTemplate": "Along the path, Barnaby spotted a {{sidekick_animal_slot}} in the {{color_slot}} morning light.",
            "baseLayers": [background_layer],
            "slots": [
                {"slotId": "sidekick_animal_slot", "slotType": "CONTROLLED_VOCAB", "slotTag": "sidekick_animal", "layerType": "prop_character", "required": True},
                {"slotId": "color_slot", "slotType": "CONTROLLED_VOCAB", "slotTag": "descriptive_color", "layerType": "prop_light", "required": True},
            ],
            "defaultValuesBySlot": {
                "sidekick_animal_slot": {"type": "asset", "assetId": "asset-fox"},
                "color_slot": {"type": "asset", "assetId": "asset-color-golden"},
            },
        },
        {
            "pageOrder": "0003",
            "textTemplate": "Feeling happy, Barnaby and his new friend {{sidekick_name_slot}} decided to nap together under the trees.",
            "baseLayers": [background_layer],
            "slots": [
                {"slotId": "sidekick_name_slot", "slotType": "CONTROLLED_VOCAB_WITH_OVERRIDE", "slotTag": "sidekick_name", "required": True},
                {"slotId": "expression_slot", "slotType": "CONTROLLED_VOCAB", "slotTag": "protagonist_expression", "layerType": "cast_expression", "required": True},
            ],
            "defaultValuesBySlot": {
                "sidekick_name_slot": {"type": "text", "value": "Pip"},
                "expression_slot": {"type": "asset", "assetId": "asset-expr-happy"},
            },
        },
    ]

    for page in pages:
        story_template_pages_table.put_item(Item={"storyTemplateId": TEMPLATE_ID, **page})


def main():
    print("Uploading placeholder art...")
    upload_placeholders()
    print("Seeding Developmental Frameworks...")
    seed_developmental_frameworks()
    print("Seeding ThemePack...")
    seed_theme_pack()
    print("Seeding Preset Cast (Barnaby the Bear)...")
    seed_preset_cast()
    print("Seeding CONTROLLED_VOCAB assets (sidekick animals, colors)...")
    seed_controlled_vocab_assets()
    print("Seeding StoryTemplate + pages...")
    seed_story_template()
    print("Done. themePackId =", PACK_ID, "/ storyTemplateId =", TEMPLATE_ID)


if __name__ == "__main__":
    main()
