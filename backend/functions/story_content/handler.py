import json
import os

import boto3

dynamodb = boto3.resource("dynamodb")
theme_packs_table = dynamodb.Table(os.environ["THEME_PACKS_TABLE"])
assets_table = dynamodb.Table(os.environ["ASSETS_TABLE"])
story_templates_table = dynamodb.Table(os.environ["STORY_TEMPLATES_TABLE"])
story_template_pages_table = dynamodb.Table(os.environ["STORY_TEMPLATE_PAGES_TABLE"])
preset_cast_members_table = dynamodb.Table(os.environ["PRESET_CAST_MEMBERS_TABLE"])
developmental_frameworks_table = dynamodb.Table(os.environ["DEVELOPMENTAL_FRAMEWORKS_TABLE"])
users_table = dynamodb.Table(os.environ["USERS_TABLE"])
households_table = dynamodb.Table(os.environ["HOUSEHOLDS_TABLE"])


def lambda_handler(event, context):
    http_method = event["httpMethod"]
    resource = event["resource"]

    if resource == "/theme-packs" and http_method == "GET":
        return list_theme_packs(event)
    elif resource == "/theme-packs/{themePackId}" and http_method == "GET":
        return get_theme_pack(event)
    elif resource == "/story-templates" and http_method == "GET":
        return list_story_templates(event)
    elif resource == "/story-templates/{storyTemplateId}" and http_method == "GET":
        return get_story_template(event)
    elif resource == "/story-templates/{storyTemplateId}/pages" and http_method == "GET":
        return list_story_template_pages(event)
    elif resource == "/preset-cast-members" and http_method == "GET":
        return list_preset_cast_members(event)
    elif resource == "/developmental-frameworks" and http_method == "GET":
        return list_developmental_frameworks(event)

    return response(404, {"message": "Not found"})


def _get_caller_id(event):
    try:
        return event["requestContext"]["authorizer"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def _caller_plan(event):
    """Every catalogue-browsing endpoint here filters by tierRequired, so
    the caller's plan is looked up once and reused rather than duplicated
    per handler."""
    caller_id = _get_caller_id(event)
    if not caller_id:
        return "free"
    user = users_table.get_item(Key={"userId": caller_id}).get("Item")
    if not user or not user.get("householdId"):
        return "free"
    household = households_table.get_item(Key={"householdId": user["householdId"]}).get("Item")
    return household.get("plan", "free") if household else "free"


def _entitled(item, plan):
    """free households only see free-tier packs; premium sees everything.
    Mirrors the existing plan/TIER_LIMITS gate from stories/handler.py
    rather than inventing a second entitlement mechanism."""
    return plan == "premium" or item.get("tierRequired", "free") == "free"


def list_theme_packs(event):
    """Global catalogue, same shape as list_books: only published packs are
    ever returned, filtered further by the caller's entitlement tier."""
    plan = _caller_plan(event)
    result = theme_packs_table.scan(
        FilterExpression="catalogueStatus = :s",
        ExpressionAttributeValues={":s": "published"},
    )
    items = [i for i in result.get("Items", []) if _entitled(i, plan)]
    return response(200, items)


def get_theme_pack(event):
    theme_pack_id = event["pathParameters"]["themePackId"]
    item = theme_packs_table.get_item(Key={"themePackId": theme_pack_id}).get("Item")
    if not item or item.get("catalogueStatus") != "published":
        return response(404, {"message": "Theme pack not found"})
    if not _entitled(item, _caller_plan(event)):
        return response(403, {"message": "This theme pack requires a premium plan."})
    return response(200, item)


def list_story_templates(event):
    """Filter params: themePackId (required) and optionally
    isQuickStoryDefault=true, which is how Tier 1 asks for the fast-path
    template instead of browsing the full customize list."""
    params = event.get("queryStringParameters") or {}
    theme_pack_id = params.get("themePackId")
    if not theme_pack_id:
        return response(400, {"message": "themePackId query parameter required"})

    pack = theme_packs_table.get_item(Key={"themePackId": theme_pack_id}).get("Item")
    if not pack or pack.get("catalogueStatus") != "published":
        return response(404, {"message": "Theme pack not found"})
    if not _entitled(pack, _caller_plan(event)):
        return response(403, {"message": "This theme pack requires a premium plan."})

    result = story_templates_table.query(
        IndexName="byThemePack",
        KeyConditionExpression="themePackId = :tid",
        ExpressionAttributeValues={":tid": theme_pack_id},
    )
    items = [i for i in result.get("Items", []) if i.get("catalogueStatus") == "published"]

    if params.get("isQuickStoryDefault") == "true":
        items = [i for i in items if i.get("isQuickStoryDefault")]
    if params.get("languageCode"):
        items = [i for i in items if i.get("languageCode", "en") == params["languageCode"]]
    if params.get("developmentalFramework"):
        framework_id = params["developmentalFramework"]
        framework = developmental_frameworks_table.get_item(
            Key={"frameworkId": framework_id}
        ).get("Item")
        if not framework or framework.get("catalogueStatus") != "published":
            return response(400, {"message": "Invalid developmental framework."})
        items = [i for i in items if i.get("developmentalFramework") == framework_id]

    return response(200, items)


def get_story_template(event):
    story_template_id = event["pathParameters"]["storyTemplateId"]
    item = story_templates_table.get_item(Key={"storyTemplateId": story_template_id}).get("Item")
    if not item or item.get("catalogueStatus") != "published":
        return response(404, {"message": "Story template not found"})
    return response(200, item)


def list_story_template_pages(event):
    story_template_id = event["pathParameters"]["storyTemplateId"]
    template = story_templates_table.get_item(Key={"storyTemplateId": story_template_id}).get("Item")
    if not template or template.get("catalogueStatus") != "published":
        return response(404, {"message": "Story template not found"})

    result = story_template_pages_table.query(
        KeyConditionExpression="storyTemplateId = :tid",
        ExpressionAttributeValues={":tid": story_template_id},
    )
    return response(200, result.get("Items", []))


def list_preset_cast_members(event):
    """Filter params: themePackId and styleId, both optional — narrows the
    roster to members with pieces actually available in that pack/style
    rather than returning the entire roster for the client to filter."""
    params = event.get("queryStringParameters") or {}
    theme_pack_id = params.get("themePackId")
    style_id = params.get("styleId")

    result = preset_cast_members_table.scan(
        FilterExpression="catalogueStatus = :s",
        ExpressionAttributeValues={":s": "published"},
    )
    items = result.get("Items", [])

    if style_id:
        items = [i for i in items if style_id in i.get("availableStyles", [])]
    if theme_pack_id:
        items = [
            i for i in items
            if not i.get("availableThemePacks") or theme_pack_id in i["availableThemePacks"]
        ]

    return response(200, items)


def list_developmental_frameworks(event):
    """Global catalogue, same scan-and-filter shape as list_theme_packs.
    No entitlement gate — frameworks aren't a paywalled concept, unlike
    ThemePacks. Serves two different callers off the same rows: the
    parent-facing wizard (displayName, parentFacingDescription) and
    internal content-production tooling (narrativeGuidance,
    creativeBriefQuestions) — no field-level filtering by caller, matching
    every other catalogue endpoint here."""
    result = developmental_frameworks_table.scan(
        FilterExpression="catalogueStatus = :s",
        ExpressionAttributeValues={":s": "published"},
    )
    return response(200, result.get("Items", []))


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
