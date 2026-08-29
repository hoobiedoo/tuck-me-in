import json
import os
import time
import uuid
from datetime import datetime

import boto3

dynamodb = boto3.resource("dynamodb")
stories_table = dynamodb.Table(os.environ["STORIES_TABLE"])
users_table = dynamodb.Table(os.environ["USERS_TABLE"])
households_table = dynamodb.Table(os.environ["HOUSEHOLDS_TABLE"])
auto_release_grants_table = dynamodb.Table(os.environ["AUTO_RELEASE_GRANTS_TABLE"])
pending_publish_notifications_table = dynamodb.Table(os.environ["PENDING_PUBLISH_NOTIFICATIONS_TABLE"])
s3_client = boto3.client("s3")
sqs_client = boto3.client("sqs")
sns_client = boto3.client("sns")

AUDIO_BUCKET = os.environ["AUDIO_BUCKET"]
AUDIO_PROCESSING_QUEUE_URL = os.environ["AUDIO_PROCESSING_QUEUE_URL"]
RECORDING_WITHDRAWN_TOPIC_ARN = os.environ["RECORDING_WITHDRAWN_TOPIC_ARN"]

# Tier-based duration limits (in seconds)
TIER_LIMITS = {
    "free": 15,
    "premium": 3600,  # 1 hour
}


def get_max_duration(household_id):
    """Get the maximum duration allowed for a household based on their plan."""
    try:
        result = households_table.get_item(Key={"householdId": household_id})
        household = result.get("Item")
        plan = household.get("plan", "free") if household else "free"
        return TIER_LIMITS.get(plan, TIER_LIMITS["free"])
    except Exception:
        return TIER_LIMITS["free"]


def lambda_handler(event, context):
    http_method = event["httpMethod"]
    resource = event["resource"]

    if resource == "/stories" and http_method == "POST":
        return create_story(event)
    elif resource == "/stories" and http_method == "GET":
        return list_stories(event)
    elif resource == "/stories/limits" and http_method == "GET":
        return get_tier_limits(event)
    elif resource == "/stories/{storyId}" and http_method == "GET":
        return get_story(event)
    elif resource == "/stories/{storyId}" and http_method == "DELETE":
        return delete_story(event)
    elif resource == "/stories/{storyId}/upload-url" and http_method == "GET":
        return get_upload_url(event)
    elif resource == "/stories/{storyId}/confirm" and http_method == "POST":
        return confirm_upload(event)
    elif resource == "/stories/{storyId}/cover-upload-url" and http_method == "GET":
        return get_cover_upload_url(event)
    elif resource == "/stories/{storyId}/publish" and http_method == "PUT":
        return publish_story(event)
    elif resource == "/stories/{storyId}/release" and http_method == "PUT":
        return release_story(event)
    elif resource == "/stories/{storyId}/unpublish" and http_method == "PUT":
        return unpublish_story(event)

    return response(404, {"message": "Not found"})


def _contributor_status(item):
    """Recordings created before this field existed have no contributorStatus
    at all — treat that as 'published' so pre-existing library content doesn't
    disappear from every list."""
    return item.get("contributorStatus") or "published"


def _is_admin(user_id, household_id):
    """Check if a user is the admin of a household."""
    if not user_id:
        return False
    result = users_table.get_item(Key={"userId": user_id})
    item = result.get("Item")
    return (
        item
        and item.get("householdId") == household_id
        and item.get("role") == "admin"
    )


def create_story(event):
    body = json.loads(event["body"])
    story_id = str(uuid.uuid4())
    audio_key = f"audio/{body['householdId']}/{story_id}.mp3"

    item = {
        "storyId": story_id,
        "householdId": body["householdId"],
        "readerId": body["readerId"],
        "readerName": body.get("readerName", "Unknown"),
        "title": body["title"],
        "audioKey": audio_key,
        "durationSeconds": 0,
        "status": "pending_upload",
        "createdAt": datetime.utcnow().isoformat(),
        "contributorStatus": "draft",
        "assignments": [],
    }

    # Optional fields
    if "coverImageUrl" in body:
        item["coverImageUrl"] = body["coverImageUrl"]

    stories_table.put_item(Item=item)
    return response(201, item)


def list_stories(event):
    params = event.get("queryStringParameters") or {}
    household_id = params.get("householdId")
    reader_id = params.get("readerId")
    view = params.get("view")
    child_id = params.get("childId")
    caller_id = _get_caller_id(event)

    if reader_id:
        result = stories_table.query(
            IndexName="byReader",
            KeyConditionExpression="readerId = :rid",
            ExpressionAttributeValues={":rid": reader_id},
        )
    elif household_id:
        result = stories_table.query(
            IndexName="byHousehold",
            KeyConditionExpression="householdId = :hid",
            ExpressionAttributeValues={":hid": household_id},
        )
    else:
        return response(400, {"message": "householdId or readerId query parameter required"})

    # Only consider stories whose audio has finished processing
    items = [i for i in result.get("Items", []) if i.get("status") == "ready"]

    if view == "drafts":
        items = [
            i for i in items
            if _contributor_status(i) == "draft" and i.get("readerId") == caller_id
        ]
    elif view == "review":
        if not household_id or not _is_admin(caller_id, household_id):
            return response(403, {"message": "Only the household admin can view the review queue."})
        items = [i for i in items if _contributor_status(i) == "published"]
    elif view == "assigned":
        if not child_id:
            return response(400, {"message": "childId query parameter required for view=assigned"})
        items = [
            i for i in items
            if _contributor_status(i) != "withdrawn"
            and any(a.get("childId") == child_id for a in i.get("assignments", []))
        ]
    else:
        # Default household/family view: everything published, plus the
        # caller's own drafts. Other people's drafts and anything withdrawn
        # are excluded.
        items = [
            i for i in items
            if _contributor_status(i) == "published"
            or (_contributor_status(i) == "draft" and i.get("readerId") == caller_id)
        ]

    return response(200, items)


def get_tier_limits(event):
    """Return the tier limits for a household."""
    params = event.get("queryStringParameters") or {}
    household_id = params.get("householdId")

    if not household_id:
        return response(400, {"message": "householdId query parameter required"})

    max_duration = get_max_duration(household_id)

    # Get household plan for client display
    try:
        result = households_table.get_item(Key={"householdId": household_id})
        household = result.get("Item")
        plan = household.get("plan", "free") if household else "free"
    except Exception:
        plan = "free"

    return response(200, {
        "plan": plan,
        "maxDurationSeconds": max_duration,
        "limits": TIER_LIMITS
    })


def get_story(event):
    story_id = event["pathParameters"]["storyId"]
    result = stories_table.get_item(Key={"storyId": story_id})
    item = result.get("Item")
    if not item:
        return response(404, {"message": "Story not found"})
    return response(200, item)


def delete_story(event):
    story_id = event["pathParameters"]["storyId"]
    result = stories_table.get_item(Key={"storyId": story_id})
    item = result.get("Item")
    if not item:
        return response(404, {"message": "Story not found"})

    # Check permissions: must be the story's recorder or household admin
    caller_id = _get_caller_id(event)
    if caller_id and caller_id != item.get("readerId"):
        # Not the recorder — check if they're an admin
        user_result = users_table.get_item(Key={"userId": caller_id})
        user = user_result.get("Item")
        if not user or user.get("role") != "admin" or user.get("householdId") != item.get("householdId"):
            return response(403, {"message": "Only the recorder or household admin can delete this story."})

    if _contributor_status(item) == "published":
        return response(400, {
            "message": "This recording has already been published for parent review. "
                       "Ask the household admin to unpublish it instead of deleting it."
        })

    # Mark as archived rather than hard delete
    stories_table.update_item(
        Key={"storyId": story_id},
        UpdateExpression="SET #s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "archived"},
    )
    return response(200, {"message": "Story archived"})


def _get_caller_id(event):
    """Extract the Cognito user ID from the request context."""
    try:
        return event["requestContext"]["authorizer"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def get_upload_url(event):
    story_id = event["pathParameters"]["storyId"]
    result = stories_table.get_item(Key={"storyId": story_id})
    item = result.get("Item")
    if not item:
        return response(404, {"message": "Story not found"})

    presigned_url = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": AUDIO_BUCKET,
            "Key": item["audioKey"],
            "ContentType": "audio/mpeg",
        },
        ExpiresIn=3600,
    )

    return response(200, {"uploadUrl": presigned_url, "audioKey": item["audioKey"]})


def confirm_upload(event):
    story_id = event["pathParameters"]["storyId"]
    result = stories_table.get_item(Key={"storyId": story_id})
    item = result.get("Item")
    if not item:
        return response(404, {"message": "Story not found"})

    if item.get("status") != "pending_upload":
        return response(400, {"message": "Story is not pending upload"})

    # Check file size and estimate duration before queueing
    max_duration = get_max_duration(item["householdId"])
    try:
        head = s3_client.head_object(Bucket=AUDIO_BUCKET, Key=item["audioKey"])
        content_length = head["ContentLength"]

        # Estimate duration from file size (128kbps MP3 ~ 16KB/sec)
        estimated_duration = int(content_length / 16000)

        if estimated_duration > max_duration:
            stories_table.update_item(
                Key={"storyId": story_id},
                UpdateExpression="SET #s = :status",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":status": "rejected_too_long"},
            )
            # Format duration message based on tier
            if max_duration < 60:
                max_msg = f"{max_duration} seconds"
            else:
                max_msg = f"{max_duration // 60} minutes"
            return response(400, {
                "message": f"Story exceeds maximum duration of {max_msg}",
                "estimatedDuration": estimated_duration,
                "maxDuration": max_duration
            })
    except Exception as e:
        return response(400, {"message": f"Could not verify upload: {str(e)}"})

    # Queue for audio processing
    sqs_client.send_message(
        QueueUrl=AUDIO_PROCESSING_QUEUE_URL,
        MessageBody=json.dumps({
            "storyId": story_id,
            "audioKey": item["audioKey"],
            "householdId": item["householdId"],
            "title": item["title"],
        }),
    )

    # Mark as queued for processing (audio processor will update to ready)
    stories_table.update_item(
        Key={"storyId": story_id},
        UpdateExpression="SET #s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "queued"},
    )

    return response(200, {"message": "Upload confirmed", "storyId": story_id})


def get_cover_upload_url(event):
    """Generate presigned URL for uploading story cover image."""
    story_id = event["pathParameters"]["storyId"]
    result = stories_table.get_item(Key={"storyId": story_id})
    item = result.get("Item")
    if not item:
        return response(404, {"message": "Story not found"})

    # Check permissions: must be the story's recorder or household admin
    caller_id = _get_caller_id(event)
    if caller_id and caller_id != item.get("readerId"):
        user_result = users_table.get_item(Key={"userId": caller_id})
        user = user_result.get("Item")
        if not user or user.get("role") != "admin" or user.get("householdId") != item.get("householdId"):
            return response(403, {"message": "Only the recorder or household admin can update cover images."})

    # Generate unique key for cover image
    cover_key = f"covers/{item['householdId']}/{story_id}.jpg"

    presigned_url = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": AUDIO_BUCKET,
            "Key": cover_key,
            "ContentType": "image/jpeg",
        },
        ExpiresIn=3600,
    )

    # Update story with cover image URL (CloudFront URL)
    cdn_domain = os.environ.get("CDN_DOMAIN", "")
    cover_url = f"https://{cdn_domain}/{cover_key}" if cdn_domain else None

    if cover_url:
        stories_table.update_item(
            Key={"storyId": story_id},
            UpdateExpression="SET coverImageUrl = :url",
            ExpressionAttributeValues={":url": cover_url},
        )

    return response(200, {"uploadUrl": presigned_url, "coverKey": cover_key, "coverImageUrl": cover_url})


def publish_story(event):
    """Contributor finalizes a draft. Auto-release grants (if any) apply
    immediately; everyone else waits for the parent's manual review."""
    story_id = event["pathParameters"]["storyId"]
    result = stories_table.get_item(Key={"storyId": story_id})
    item = result.get("Item")
    if not item:
        return response(404, {"message": "Story not found"})

    caller_id = _get_caller_id(event)
    if caller_id != item.get("readerId"):
        return response(403, {"message": "Only the recording's own contributor can publish it."})

    status = _contributor_status(item)
    if status == "withdrawn":
        return response(400, {"message": "This recording was withdrawn and can't be republished. Record a new one instead."})
    if status == "published":
        return response(200, item)

    now = datetime.utcnow().isoformat()
    assignments = list(item.get("assignments", []))
    already_assigned = {a["childId"] for a in assignments}

    grants = auto_release_grants_table.query(
        KeyConditionExpression="contributorId = :cid",
        ExpressionAttributeValues={":cid": caller_id},
    ).get("Items", [])

    for grant in grants:
        if grant.get("householdId") != item.get("householdId"):
            continue
        if grant["childId"] in already_assigned:
            continue
        assignments.append({
            "childId": grant["childId"],
            "assignedAt": now,
            "releasedAt": now,
            "releasedBy": "auto",
        })

    updated = stories_table.update_item(
        Key={"storyId": story_id},
        UpdateExpression="SET contributorStatus = :s, publishedAt = :p, assignments = :a",
        ExpressionAttributeValues={":s": "published", ":p": now, ":a": assignments},
        ReturnValues="ALL_NEW",
    )["Attributes"]

    _append_to_publish_window(item["householdId"], story_id)

    return response(200, updated)


def _append_to_publish_window(household_id, story_id):
    """Batches 'published' events into one digest per household instead of
    notifying the parent once per recording."""
    now = datetime.utcnow().isoformat()
    latest = pending_publish_notifications_table.query(
        KeyConditionExpression="householdId = :hid",
        ExpressionAttributeValues={":hid": household_id},
        ScanIndexForward=False,
        Limit=1,
    ).get("Items", [])

    if latest:
        window = latest[0]
        pending_publish_notifications_table.update_item(
            Key={"householdId": household_id, "windowStartedAt": window["windowStartedAt"]},
            UpdateExpression="SET recordingIds = list_append(recordingIds, :sid)",
            ExpressionAttributeValues={":sid": [story_id]},
        )
    else:
        pending_publish_notifications_table.put_item(Item={
            "householdId": household_id,
            "windowStartedAt": now,
            "recordingIds": [story_id],
            "ttl": int(time.time()) + 3600,
        })


def release_story(event):
    """Admin assigns a published recording to one or more children, making it
    visible on their Home Screen."""
    story_id = event["pathParameters"]["storyId"]
    result = stories_table.get_item(Key={"storyId": story_id})
    item = result.get("Item")
    if not item:
        return response(404, {"message": "Story not found"})

    caller_id = _get_caller_id(event)
    if not _is_admin(caller_id, item["householdId"]):
        return response(403, {"message": "Only the household admin can release recordings."})

    status = _contributor_status(item)
    if status != "published":
        return response(400, {"message": "Only published recordings can be released."})

    body = json.loads(event["body"])
    child_ids = body.get("childIds") or []
    if not child_ids:
        return response(400, {"message": "childIds is required."})

    now = datetime.utcnow().isoformat()
    assignments = list(item.get("assignments", []))
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

    updated = stories_table.update_item(
        Key={"storyId": story_id},
        UpdateExpression="SET assignments = :a",
        ExpressionAttributeValues={":a": assignments},
        ReturnValues="ALL_NEW",
    )["Attributes"]

    return response(200, updated)


def unpublish_story(event):
    """Admin pulls a recording back, from either Published or Released. Works
    the same way regardless of which state it's coming from, and never
    reverts to Draft."""
    story_id = event["pathParameters"]["storyId"]
    result = stories_table.get_item(Key={"storyId": story_id})
    item = result.get("Item")
    if not item:
        return response(404, {"message": "Story not found"})

    caller_id = _get_caller_id(event)
    if not _is_admin(caller_id, item["householdId"]):
        return response(403, {"message": "Only the household admin can unpublish recordings."})

    status = _contributor_status(item)
    if status in ("draft", "withdrawn"):
        return response(400, {"message": "This recording isn't currently published or released."})

    now = datetime.utcnow().isoformat()
    updated = stories_table.update_item(
        Key={"storyId": story_id},
        UpdateExpression="SET contributorStatus = :s, withdrawnAt = :w",
        ExpressionAttributeValues={":s": "withdrawn", ":w": now},
        ReturnValues="ALL_NEW",
    )["Attributes"]

    households_table.update_item(
        Key={"householdId": item["householdId"]},
        UpdateExpression="ADD contentVersion :one",
        ExpressionAttributeValues={":one": 1},
    )

    sns_client.publish(
        TopicArn=RECORDING_WITHDRAWN_TOPIC_ARN,
        Subject="Recording No Longer Active",
        Message=json.dumps({
            "storyId": story_id,
            "contributorId": item.get("readerId"),
            "title": item.get("title"),
            "message": f"Your recording of {item.get('title')} is no longer active.",
        }),
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
