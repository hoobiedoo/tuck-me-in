import json
import os
import uuid
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
theme_packs_table = dynamodb.Table(os.environ["THEME_PACKS_TABLE"])
assets_table = dynamodb.Table(os.environ["ASSETS_TABLE"])
story_templates_table = dynamodb.Table(os.environ["STORY_TEMPLATES_TABLE"])
story_template_pages_table = dynamodb.Table(os.environ["STORY_TEMPLATE_PAGES_TABLE"])
preset_cast_members_table = dynamodb.Table(os.environ["PRESET_CAST_MEMBERS_TABLE"])
developmental_frameworks_table = dynamodb.Table(os.environ["DEVELOPMENTAL_FRAMEWORKS_TABLE"])
story_instances_table = dynamodb.Table(os.environ["STORY_INSTANCES_TABLE"])
story_instance_pages_table = dynamodb.Table(os.environ["STORY_INSTANCE_PAGES_TABLE"])
story_instance_takes_table = dynamodb.Table(os.environ["STORY_INSTANCE_TAKES_TABLE"])
story_instance_segment_recordings_table = dynamodb.Table(os.environ["STORY_INSTANCE_SEGMENT_RECORDINGS_TABLE"])
auto_release_grants_table = dynamodb.Table(os.environ["AUTO_RELEASE_GRANTS_TABLE"])
households_table = dynamodb.Table(os.environ["HOUSEHOLDS_TABLE"])
users_table = dynamodb.Table(os.environ["USERS_TABLE"])

# Text/proper-noun override slots never touch a model or an Asset lookup —
# this is the only length guard applied to them.
MAX_OVERRIDE_TEXT_LENGTH = 40


def lambda_handler(event, context):
    http_method = event["httpMethod"]
    resource = event["resource"]

    if resource == "/story-instances" and http_method == "POST":
        return create_story_instance(event)
    elif resource == "/story-instances" and http_method == "GET":
        return list_story_instances(event)
    elif resource == "/story-instances/{storyInstanceId}" and http_method == "GET":
        return get_story_instance(event)
    elif resource == "/story-instances/{storyInstanceId}/current-page" and http_method == "PUT":
        return update_current_page(event)
    elif resource == "/story-instances/{storyInstanceId}/pages/{pageOrder}" and http_method == "GET":
        return get_page(event)
    elif resource == "/story-instances/{storyInstanceId}/pages/{pageOrder}/slot-options" and http_method == "GET":
        return get_slot_options(event)
    elif resource == "/story-instances/{storyInstanceId}/pages/{pageOrder}/slots" and http_method == "PUT":
        return write_slots(event)
    elif resource == "/story-instances/{storyInstanceId}/publish" and http_method == "PUT":
        return publish_story_instance(event)
    elif resource == "/story-instances/{storyInstanceId}/release" and http_method == "PUT":
        return release_story_instance(event)
    elif resource == "/story-instances/{storyInstanceId}/unpublish" and http_method == "PUT":
        return unpublish_story_instance(event)

    return response(404, {"message": "Not found"})


# --- auth helpers ---

def _get_caller_id(event):
    try:
        return event["requestContext"]["authorizer"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def _get_household_id(caller_id):
    if not caller_id:
        return None
    item = users_table.get_item(Key={"userId": caller_id}).get("Item")
    return item.get("householdId") if item else None


def _is_admin(user_id, household_id):
    if not user_id:
        return False
    item = users_table.get_item(Key={"userId": user_id}).get("Item")
    return (
        item
        and item.get("householdId") == household_id
        and item.get("role") == "admin"
    )


def _contributor_status(item):
    return item.get("contributorStatus") or "draft"


# --- page-order helper ---

def _page_order_key(index):
    """Zero-padded, same convention as BookSegments.segmentOrder — gives
    native reading-order queries with no extra GSI."""
    return f"{index:04d}"


# --- Phase 1: initialization ---

def create_story_instance(event):
    caller_id = _get_caller_id(event)
    household_id = _get_household_id(caller_id)
    if not caller_id or not household_id:
        return response(403, {"message": "Must be an authenticated household member."})

    body = json.loads(event["body"])
    theme_pack_id = body.get("themePackId")
    style_id = body.get("styleId")
    developmental_framework = body.get("developmentalFramework")
    story_template_id = body.get("storyTemplateId")
    cast_selection = body.get("castSelection") or {}
    quick_fill = bool(body.get("quickFill"))

    if not all([theme_pack_id, style_id, developmental_framework, story_template_id]):
        return response(400, {
            "message": "themePackId, styleId, developmentalFramework, and storyTemplateId are required."
        })

    if cast_selection.get("type") == "character":
        # Family photo-cutout Characters aren't built yet anywhere in this
        # app (upload flow, storage, management screen) — v1 of this
        # wizard is Preset Cast only. See the design proposal, §8.
        return response(400, {
            "message": "Selecting a saved family Character isn't available yet — choose a Preset Cast member."
        })
    if cast_selection.get("type") != "preset" or not cast_selection.get("castMemberId"):
        return response(400, {"message": "castSelection must be {type: 'preset', castMemberId}."})

    pack = theme_packs_table.get_item(Key={"themePackId": theme_pack_id}).get("Item")
    if not pack or pack.get("catalogueStatus") != "published":
        return response(404, {"message": "Theme pack not found."})
    if style_id not in pack.get("styles", []):
        return response(400, {"message": f"Style '{style_id}' isn't available in this theme pack."})

    framework = developmental_frameworks_table.get_item(
        Key={"frameworkId": developmental_framework}
    ).get("Item")
    if not framework or framework.get("catalogueStatus") != "published":
        return response(400, {"message": f"'{developmental_framework}' isn't a valid developmental framework."})

    template = story_templates_table.get_item(Key={"storyTemplateId": story_template_id}).get("Item")
    if not template or template.get("catalogueStatus") != "published" or template.get("themePackId") != theme_pack_id:
        return response(404, {"message": "Story template not found in this theme pack."})
    if template.get("developmentalFramework") != developmental_framework:
        return response(400, {"message": "Story template does not belong to the selected developmental framework."})
    if template.get("castMemberId") and template["castMemberId"] != cast_selection.get("castMemberId"):
        return response(400, {"message": "Story template does not belong to the selected cast member."})

    template_pages = _load_template_pages(story_template_id)
    if not template_pages:
        return response(400, {"message": "This story template has no pages."})

    story_instance_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    instance_item = {
        "storyInstanceId": story_instance_id,
        "householdId": household_id,
        "createdBy": caller_id,
        "themePackId": theme_pack_id,
        "styleId": style_id,
        "developmentalFramework": developmental_framework,
        "storyTemplateId": story_template_id,
        "languageCode": template.get("languageCode", "en"),
        "translationGroupId": template.get("translationGroupId", story_template_id),
        "castSelection": cast_selection,
        "currentPageOrder": template_pages[0]["pageOrder"],
        "contributorStatus": "draft",
        "assignments": [],
        "createdAt": now,
    }
    story_instances_table.put_item(Item=instance_item)

    for template_page in template_pages:
        filled_slot_values = {}
        if quick_fill:
            # defaultValuesBySlot holds the same {type: "asset"|"text", ...}
            # shape filledSlotValues does, so both slot types get a sane
            # Quick Story default — not just CONTROLLED_VOCAB ones.
            defaults = template_page.get("defaultValuesBySlot", {})
            for slot in template_page.get("slots", []):
                default_value = defaults.get(slot["slotId"])
                if default_value:
                    filled_slot_values[slot["slotId"]] = default_value
        _write_page(
            story_instance_id, theme_pack_id, style_id, cast_selection,
            template_page, filled_slot_values, template.get("languageCode", "en"),
        )

    return response(201, instance_item)


# --- listing / reading ---

def list_story_instances(event):
    params = event.get("queryStringParameters") or {}
    household_id = params.get("householdId")
    if not household_id:
        return response(400, {"message": "householdId query parameter required"})
    caller_id = _get_caller_id(event)

    result = story_instances_table.query(
        IndexName="byHousehold",
        KeyConditionExpression="householdId = :hid",
        ExpressionAttributeValues={":hid": household_id},
    )
    items = [
        i for i in result.get("Items", [])
        if _contributor_status(i) != "draft" or i.get("createdBy") == caller_id
    ]
    return response(200, items)


def get_story_instance(event):
    story_instance_id = event["pathParameters"]["storyInstanceId"]
    item = story_instances_table.get_item(Key={"storyInstanceId": story_instance_id}).get("Item")
    if not item:
        return response(404, {"message": "Story instance not found"})
    return response(200, item)


def update_current_page(event):
    """The resume pointer — bumped on page-advance, never on a slot edit."""
    story_instance_id = event["pathParameters"]["storyInstanceId"]
    body = json.loads(event["body"])
    page_order = body.get("pageOrder")
    if not page_order:
        return response(400, {"message": "pageOrder is required."})

    if not story_instances_table.get_item(Key={"storyInstanceId": story_instance_id}).get("Item"):
        return response(404, {"message": "Story instance not found"})

    story_instances_table.update_item(
        Key={"storyInstanceId": story_instance_id},
        UpdateExpression="SET currentPageOrder = :p",
        ExpressionAttributeValues={":p": page_order},
    )
    return response(200, {"currentPageOrder": page_order})


def get_page(event):
    story_instance_id = event["pathParameters"]["storyInstanceId"]
    page_order = event["pathParameters"]["pageOrder"]
    item = story_instance_pages_table.get_item(
        Key={"storyInstanceId": story_instance_id, "pageOrder": page_order}
    ).get("Item")
    if not item:
        return response(404, {"message": "Page not found"})
    return response(200, item)


# --- Phase 2: slot resolution (§3) ---

def get_slot_options(event):
    """Resolves every slot on a page in one call: CONTROLLED_VOCAB slots
    query byPackStyleSlot directly (no cross-pack fallback is possible —
    nothing outside that partition is ever read); CONTROLLED_VOCAB_WITH_OVERRIDE
    slots return the theme pack's own suggestion list for that slotTag."""
    story_instance_id = event["pathParameters"]["storyInstanceId"]
    page_order = event["pathParameters"]["pageOrder"]

    instance = story_instances_table.get_item(Key={"storyInstanceId": story_instance_id}).get("Item")
    if not instance:
        return response(404, {"message": "Story instance not found"})

    template_page = story_template_pages_table.get_item(
        Key={"storyTemplateId": instance["storyTemplateId"], "pageOrder": page_order}
    ).get("Item")
    if not template_page:
        return response(404, {"message": "Page not found"})

    pack = theme_packs_table.get_item(Key={"themePackId": instance["themePackId"]}).get("Item") or {}
    cast_member_id = instance["castSelection"].get("castMemberId")

    options = {}
    for slot in template_page.get("slots", []):
        if slot["slotType"] == "CONTROLLED_VOCAB":
            candidates = _query_pack_style_slot(
                instance["themePackId"], instance["styleId"], slot["slotTag"],
                instance.get("languageCode", "en"),
            )
            if slot.get("layerType") == "cast_expression":
                candidates = [a for a in candidates if a.get("castMemberId") == cast_member_id]
            options[slot["slotId"]] = candidates
        elif slot["slotType"] == "CONTROLLED_VOCAB_WITH_OVERRIDE":
            suggestions = _language_values(
                pack.get("nameSuggestions", {}).get(slot["slotTag"], []),
                instance.get("languageCode", "en"),
            )
            options[slot["slotId"]] = {"suggestions": suggestions, "allowOverride": True}

    return response(200, options)


def _query_pack_style_slot(theme_pack_id, style_id, slot_tag, language_code="en"):
    key = f"{theme_pack_id}#{style_id}#{slot_tag}"
    result = assets_table.query(
        IndexName="byPackStyleSlot",
        KeyConditionExpression="packStyleSlotKey = :k",
        ExpressionAttributeValues={":k": key},
    )
    items = [a for a in result.get("Items", []) if a.get("reviewStatus") == "published"]
    return [{**asset, "displayLabel": _language_value(asset.get("displayLabel"), language_code)} for asset in items]


def _language_values(value, language_code):
    """Read the new language-keyed suggestion shape with legacy English fallback."""
    if isinstance(value, dict):
        return value.get(language_code, [])
    return value if language_code == "en" else []


def _language_value(value, language_code):
    """Read a localized value while remaining compatible with legacy strings."""
    if isinstance(value, dict):
        return value.get(language_code) or value.get("en", "")
    return value or ""


# --- Phase 2/3/4: slot writes ---

def write_slots(event):
    """One page's slot picks, written and resolved atomically. Handles two
    rules from the design proposal's §6:
      - editing a page with a current take supersedes it (never blocks
        the edit, never leaves stale audio marked as current)
      - editing any page while contributorStatus == published reverts the
        instance to draft, so the admin never reviews a moving target
    Allowed any time up to release — assignments[] non-empty is the actual
    freeze point, not published."""
    story_instance_id = event["pathParameters"]["storyInstanceId"]
    page_order = event["pathParameters"]["pageOrder"]
    caller_id = _get_caller_id(event)

    instance = story_instances_table.get_item(Key={"storyInstanceId": story_instance_id}).get("Item")
    if not instance:
        return response(404, {"message": "Story instance not found"})
    if instance.get("createdBy") != caller_id:
        return response(403, {"message": "Only the story's own creator can edit it."})
    if instance.get("assignments"):
        return response(400, {"message": "This story has already been released and can no longer be edited."})

    template_page = story_template_pages_table.get_item(
        Key={"storyTemplateId": instance["storyTemplateId"], "pageOrder": page_order}
    ).get("Item")
    if not template_page:
        return response(404, {"message": "Page not found"})

    body = json.loads(event["body"])
    new_values = body.get("slots") or {}

    slot_defs = {s["slotId"]: s for s in template_page.get("slots", [])}
    for slot_id, value in new_values.items():
        slot_def = slot_defs.get(slot_id)
        if not slot_def:
            return response(400, {"message": f"Unknown slot '{slot_id}' for this page."})
        error = _validate_slot_value(instance, slot_def, value)
        if error:
            return response(400, {"message": error})

    existing_page = story_instance_pages_table.get_item(
        Key={"storyInstanceId": story_instance_id, "pageOrder": page_order}
    ).get("Item") or {}
    filled_slot_values = dict(existing_page.get("filledSlotValues", {}))
    filled_slot_values.update(new_values)

    _write_page(
        story_instance_id, instance["themePackId"], instance["styleId"],
        instance["castSelection"], template_page, filled_slot_values,
        instance.get("languageCode", "en"),
    )

    _supersede_take_if_any(story_instance_id, page_order)

    if _contributor_status(instance) == "published":
        story_instances_table.update_item(
            Key={"storyInstanceId": story_instance_id},
            UpdateExpression="SET contributorStatus = :s",
            ExpressionAttributeValues={":s": "draft"},
        )

    updated_page = story_instance_pages_table.get_item(
        Key={"storyInstanceId": story_instance_id, "pageOrder": page_order}
    ).get("Item")
    return response(200, updated_page)


def _validate_slot_value(instance, slot_def, value):
    if slot_def["slotType"] == "CONTROLLED_VOCAB":
        if value.get("type") != "asset" or not value.get("assetId"):
            return f"Slot '{slot_def['slotId']}' requires an asset pick."
        asset = assets_table.get_item(Key={"assetId": value["assetId"]}).get("Item")
        if not asset or asset.get("reviewStatus") != "published":
            return "Selected asset is not available."
        expected_key = f"{instance['themePackId']}#{instance['styleId']}#{slot_def['slotTag']}"
        if asset.get("packStyleSlotKey") != expected_key:
            # The strict-scoping rule enforced server-side too, not just by
            # what the picker offered — never trust the client's assetId blindly.
            return "Selected asset doesn't belong to this theme pack, style, and slot."
        return None
    elif slot_def["slotType"] == "CONTROLLED_VOCAB_WITH_OVERRIDE":
        if value.get("type") == "asset":
            return None  # picked one of the curated suggestions, treated as text below anyway
        text = (value.get("value") or "").strip()
        if not text:
            return f"Slot '{slot_def['slotId']}' can't be empty."
        if len(text) > MAX_OVERRIDE_TEXT_LENGTH:
            return f"Slot '{slot_def['slotId']}' must be {MAX_OVERRIDE_TEXT_LENGTH} characters or fewer."
        return None
    return f"Unknown slot type for '{slot_def['slotId']}'."


def _write_page(
    story_instance_id, theme_pack_id, style_id, cast_selection,
    template_page, filled_slot_values, language_code="en",
):
    resolved_text, composition_spec = _resolve_page(
        theme_pack_id, style_id, cast_selection, template_page,
        filled_slot_values, language_code,
    )
    story_instance_pages_table.put_item(Item={
        "storyInstanceId": story_instance_id,
        "pageOrder": template_page["pageOrder"],
        "filledSlotValues": filled_slot_values,
        "resolvedText": resolved_text,
        "compositionSpec": composition_spec,
        "updatedAt": datetime.utcnow().isoformat(),
    })


def _resolve_page(
    theme_pack_id, style_id, cast_selection, template_page,
    filled_slot_values, language_code="en",
):
    """The one path that produces resolvedText and compositionSpec — used
    by both instance creation (quick fill) and every slot write, so the two
    can never drift out of sync with each other."""
    text = template_page.get("textTemplate", "")
    layers = list(template_page.get("baseLayers", []))
    layers.extend(_cast_base_layers(cast_selection, style_id))

    for slot in template_page.get("slots", []):
        value = filled_slot_values.get(slot["slotId"])
        if not value:
            continue
        if value.get("type") == "asset":
            asset = assets_table.get_item(Key={"assetId": value["assetId"]}).get("Item")
            if not asset:
                continue
            text = text.replace(
                f"{{{{{slot['slotId']}}}}}",
                _language_value(asset.get("displayLabel"), language_code),
            )
            layers.append({
                "assetId": asset["assetId"],
                "cdnKey": asset.get("cdnKey"),
                "depthGroup": asset.get("depthGroup"),
                "zIndex": asset.get("zIndexDefault"),
                "transform": asset.get("transform"),
            })
        elif value.get("type") == "text":
            text = text.replace(f"{{{{{slot['slotId']}}}}}", value.get("value", ""))

    layers.sort(key=lambda l: l.get("zIndex") or 0)
    return text, layers


def _cast_base_layers(cast_selection, style_id):
    """The locked cast member's constant body pieces — present on every
    page regardless of slot picks, looked up by castMemberId + styleId
    since these aren't theme-pack-scoped."""
    cast_member_id = cast_selection.get("castMemberId")
    if not cast_member_id:
        return []
    key = f"{cast_member_id}#{style_id}"
    result = assets_table.query(
        IndexName="byCastMemberStyle",
        KeyConditionExpression="castMemberStyleKey = :k",
        ExpressionAttributeValues={":k": key},
    )
    return [
        {
            "assetId": a["assetId"],
            "cdnKey": a.get("cdnKey"),
            "depthGroup": a.get("depthGroup"),
            "zIndex": a.get("zIndexDefault"),
            "transform": a.get("transform"),
        }
        for a in result.get("Items", [])
        if a.get("layerType") == "cast_base" and a.get("reviewStatus") == "published"
    ]


def _supersede_take_if_any(story_instance_id, page_order):
    """If this page already has a current take, mark it superseded — same
    status value the Books feature's confirm_take already uses for 'a
    newer take beat this one to the punch', applied here to a second
    trigger: the text underneath the take changed instead."""
    recording = story_instance_segment_recordings_table.get_item(
        Key={"storyInstanceId": story_instance_id, "pageOrder": page_order}
    ).get("Item")
    if not recording or not recording.get("currentTakeId"):
        return

    story_instance_takes_table.update_item(
        Key={"takeId": recording["currentTakeId"]},
        UpdateExpression="SET alignmentStatus = :s",
        ExpressionAttributeValues={":s": "superseded"},
    )
    story_instance_segment_recordings_table.update_item(
        Key={"storyInstanceId": story_instance_id, "pageOrder": page_order},
        UpdateExpression="REMOVE currentTakeId",
    )


# --- content lifecycle ---

def _load_template_pages(story_template_id):
    result = story_template_pages_table.query(
        KeyConditionExpression="storyTemplateId = :tid",
        ExpressionAttributeValues={":tid": story_template_id},
    )
    return sorted(result.get("Items", []), key=lambda p: p["pageOrder"])


def publish_story_instance(event):
    story_instance_id = event["pathParameters"]["storyInstanceId"]
    caller_id = _get_caller_id(event)

    instance = story_instances_table.get_item(Key={"storyInstanceId": story_instance_id}).get("Item")
    if not instance:
        return response(404, {"message": "Story instance not found"})
    if instance.get("createdBy") != caller_id:
        return response(403, {"message": "Only the story's own creator can publish it."})

    status = _contributor_status(instance)
    if status == "withdrawn":
        return response(400, {"message": "This story was withdrawn and can't be republished."})
    if status == "published":
        return response(200, instance)

    template_pages = _load_template_pages(instance["storyTemplateId"])
    pages = story_instance_pages_table.query(
        KeyConditionExpression="storyInstanceId = :sid",
        ExpressionAttributeValues={":sid": story_instance_id},
    ).get("Items", [])
    pages_by_order = {p["pageOrder"]: p for p in pages}

    incomplete = _incomplete_slots(template_pages, pages_by_order)
    if incomplete:
        return response(400, {
            "message": "Every page needs its required words picked before publishing.",
            "incompletePages": incomplete,
        })

    narrated, unnarrated = _narration_split(story_instance_id, template_pages)
    if narrated and unnarrated:
        return response(400, {
            "message": (
                "This story can publish with no narration, or with every page narrated — "
                "not some pages narrated and others silent."
            ),
            "pagesNeedingATake": unnarrated,
        })

    now = datetime.utcnow().isoformat()
    assignments = list(instance.get("assignments", []))
    already_assigned = {a["childId"] for a in assignments}

    grants = auto_release_grants_table.query(
        KeyConditionExpression="contributorId = :cid",
        ExpressionAttributeValues={":cid": caller_id},
    ).get("Items", [])
    for grant in grants:
        if grant.get("householdId") != instance.get("householdId"):
            continue
        if grant["childId"] in already_assigned:
            continue
        assignments.append({
            "childId": grant["childId"],
            "assignedAt": now,
            "releasedAt": now,
            "releasedBy": "auto",
        })

    updated = story_instances_table.update_item(
        Key={"storyInstanceId": story_instance_id},
        UpdateExpression="SET contributorStatus = :s, publishedAt = :p, assignments = :a",
        ExpressionAttributeValues={":s": "published", ":p": now, ":a": assignments},
        ReturnValues="ALL_NEW",
    )["Attributes"]
    return response(200, updated)


def _incomplete_slots(template_pages, pages_by_order):
    incomplete = []
    for template_page in template_pages:
        page = pages_by_order.get(template_page["pageOrder"], {})
        filled = page.get("filledSlotValues", {})
        required_slot_ids = [
            s["slotId"] for s in template_page.get("slots", []) if s.get("required", True)
        ]
        if any(slot_id not in filled for slot_id in required_slot_ids):
            incomplete.append(template_page["pageOrder"])
    return incomplete


def _narration_split(story_instance_id, template_pages):
    """Returns (narratedPageOrders, unnarratedPageOrders). A page counts as
    narrated only if it has a current, non-superseded take — a page a slot
    edit orphaned looks identical to one nobody ever recorded, which is
    exactly the point: one condition to check, not two categories."""
    narrated, unnarrated = [], []
    for template_page in template_pages:
        page_order = template_page["pageOrder"]
        recording = story_instance_segment_recordings_table.get_item(
            Key={"storyInstanceId": story_instance_id, "pageOrder": page_order}
        ).get("Item")
        if recording and recording.get("currentTakeId"):
            narrated.append(page_order)
        else:
            unnarrated.append(page_order)
    return narrated, unnarrated


def release_story_instance(event):
    story_instance_id = event["pathParameters"]["storyInstanceId"]
    caller_id = _get_caller_id(event)

    instance = story_instances_table.get_item(Key={"storyInstanceId": story_instance_id}).get("Item")
    if not instance:
        return response(404, {"message": "Story instance not found"})
    if not _is_admin(caller_id, instance["householdId"]):
        return response(403, {"message": "Only the household admin can release stories."})
    if _contributor_status(instance) != "published":
        return response(400, {"message": "Only published stories can be released."})

    body = json.loads(event["body"])
    child_ids = body.get("childIds") or []
    if not child_ids:
        return response(400, {"message": "childIds is required."})

    now = datetime.utcnow().isoformat()
    assignments = list(instance.get("assignments", []))
    already_assigned = {a["childId"] for a in assignments}
    for child_id in child_ids:
        if child_id in already_assigned:
            continue
        assignments.append({
            "childId": child_id,
            "assignedAt": now,
            "releasedAt": now,
            "releasedBy": "parent",
        })

    updated = story_instances_table.update_item(
        Key={"storyInstanceId": story_instance_id},
        UpdateExpression="SET assignments = :a",
        ExpressionAttributeValues={":a": assignments},
        ReturnValues="ALL_NEW",
    )["Attributes"]
    return response(200, updated)


def unpublish_story_instance(event):
    story_instance_id = event["pathParameters"]["storyInstanceId"]
    caller_id = _get_caller_id(event)

    instance = story_instances_table.get_item(Key={"storyInstanceId": story_instance_id}).get("Item")
    if not instance:
        return response(404, {"message": "Story instance not found"})
    if not _is_admin(caller_id, instance["householdId"]):
        return response(403, {"message": "Only the household admin can unpublish stories."})

    status = _contributor_status(instance)
    if status in ("draft", "withdrawn"):
        return response(400, {"message": "This story isn't currently published or released."})

    now = datetime.utcnow().isoformat()
    updated = story_instances_table.update_item(
        Key={"storyInstanceId": story_instance_id},
        UpdateExpression="SET contributorStatus = :s, withdrawnAt = :w",
        ExpressionAttributeValues={":s": "withdrawn", ":w": now},
        ReturnValues="ALL_NEW",
    )["Attributes"]

    households_table.update_item(
        Key={"householdId": instance["householdId"]},
        UpdateExpression="ADD contentVersion :one",
        ExpressionAttributeValues={":one": 1},
    )
    return response(200, updated)


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
