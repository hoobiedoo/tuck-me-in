import json
import os
import uuid
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
story_instances_table = dynamodb.Table(os.environ["STORY_INSTANCES_TABLE"])
story_instance_pages_table = dynamodb.Table(os.environ["STORY_INSTANCE_PAGES_TABLE"])
story_instance_takes_table = dynamodb.Table(os.environ["STORY_INSTANCE_TAKES_TABLE"])
story_instance_segment_recordings_table = dynamodb.Table(os.environ["STORY_INSTANCE_SEGMENT_RECORDINGS_TABLE"])
users_table = dynamodb.Table(os.environ["USERS_TABLE"])
s3_client = boto3.client("s3")
sqs_client = boto3.client("sqs")

AUDIO_BUCKET = os.environ["AUDIO_BUCKET"]
ALIGNMENT_QUEUE_URL = os.environ["ALIGNMENT_QUEUE_URL"]


def lambda_handler(event, context):
    http_method = event["httpMethod"]
    resource = event["resource"]

    if resource == "/story-instance-takes" and http_method == "POST":
        return begin_take(event)
    elif resource == "/story-instance-takes/{takeId}/confirm" and http_method == "POST":
        return confirm_take(event)

    return response(404, {"message": "Not found"})


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


def begin_take(event):
    """One narrator per StoryInstance, set on the first take and enforced
    on every one after. Recording is allowed through draft and published —
    the freeze point is release (assignments non-empty), not publish, since
    that's the point a child can actually be exposed to a mismatch."""
    caller_id = _get_caller_id(event)
    household_id = _get_household_id(caller_id)
    if not caller_id or not household_id:
        return response(403, {"message": "Must be an authenticated household member to record."})

    body = json.loads(event["body"])
    story_instance_id = body.get("storyInstanceId")
    page_order = body.get("pageOrder")
    if not story_instance_id or not page_order:
        return response(400, {"message": "storyInstanceId and pageOrder are required."})

    instance = story_instances_table.get_item(Key={"storyInstanceId": story_instance_id}).get("Item")
    if not instance or instance.get("householdId") != household_id:
        return response(404, {"message": "Story instance not found."})
    if instance.get("assignments"):
        return response(400, {"message": "This story has already been released and can no longer be narrated."})
    if (instance.get("contributorStatus") or "draft") == "withdrawn":
        return response(400, {"message": "This story was withdrawn."})

    narrator_id = instance.get("narratorId")
    if narrator_id and narrator_id != caller_id:
        return response(403, {"message": "This story already has a narrator — only they can add takes."})

    page = story_instance_pages_table.get_item(
        Key={"storyInstanceId": story_instance_id, "pageOrder": page_order}
    ).get("Item")
    if not page or not page.get("resolvedText"):
        return response(400, {"message": "This page hasn't had its words picked yet — nothing to record against."})

    if not narrator_id:
        story_instances_table.update_item(
            Key={"storyInstanceId": story_instance_id},
            UpdateExpression="SET narratorId = :n",
            ExpressionAttributeValues={":n": caller_id},
        )

    now = datetime.utcnow().isoformat()
    updated = story_instance_segment_recordings_table.update_item(
        Key={"storyInstanceId": story_instance_id, "pageOrder": page_order},
        UpdateExpression=(
            "ADD currentTakeNumber :one "
            "SET narratorId = :nid, uploadStatus = :uploading, "
            "alignmentStatus = :notUploaded, alignmentData = :none, updatedAt = :now"
        ),
        ExpressionAttributeValues={
            ":one": 1,
            ":nid": caller_id,
            ":uploading": "uploading",
            ":notUploaded": "not_uploaded",
            ":none": None,
            ":now": now,
        },
        ReturnValues="ALL_NEW",
    )["Attributes"]

    take_number = int(updated["currentTakeNumber"])
    take_id = str(uuid.uuid4())
    audio_key = f"audio-takes/story-instances/{story_instance_id}/{page_order}/{take_id}.mp3"

    story_instance_takes_table.put_item(Item={
        "takeId": take_id,
        "segmentSlotKey": f"{story_instance_id}#{page_order}",
        "takeNumber": take_number,
        "storyInstanceId": story_instance_id,
        "pageOrder": page_order,
        "narratorId": caller_id,
        "householdId": household_id,
        "audioKey": audio_key,
        "uploadStatus": "local_only",
        "alignmentStatus": "not_uploaded",
        "recordedAt": now,
    })

    story_instance_segment_recordings_table.update_item(
        Key={"storyInstanceId": story_instance_id, "pageOrder": page_order},
        UpdateExpression="SET currentTakeId = :tid",
        ExpressionAttributeValues={":tid": take_id},
    )

    presigned_url = s3_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": AUDIO_BUCKET, "Key": audio_key, "ContentType": "audio/mpeg"},
        ExpiresIn=3600,
    )

    return response(201, {
        "takeId": take_id,
        "takeNumber": take_number,
        "uploadUrl": presigned_url,
        "audioKey": audio_key,
    })


def confirm_take(event):
    """Same race guard as the Books feature's confirm_take: only enqueue
    alignment if this take is still current. The alignment_processor's own
    conditional write is the authoritative guard if a race slips past this
    one — this is defense-in-depth, not the only check."""
    take_id = event["pathParameters"]["takeId"]
    caller_id = _get_caller_id(event)

    take = story_instance_takes_table.get_item(Key={"takeId": take_id}).get("Item")
    if not take:
        return response(404, {"message": "Take not found"})
    if take.get("narratorId") != caller_id:
        return response(403, {"message": "Not your take."})

    try:
        s3_client.head_object(Bucket=AUDIO_BUCKET, Key=take["audioKey"])
    except ClientError:
        return response(400, {"message": "Upload not found — PUT the audio before confirming."})

    now = datetime.utcnow().isoformat()
    story_instance_id, page_order = take["storyInstanceId"], take["pageOrder"]

    try:
        story_instance_segment_recordings_table.update_item(
            Key={"storyInstanceId": story_instance_id, "pageOrder": page_order},
            UpdateExpression="SET uploadStatus = :uploaded, alignmentStatus = :pending, updatedAt = :now",
            ConditionExpression="currentTakeNumber = :expected",
            ExpressionAttributeValues={
                ":uploaded": "uploaded",
                ":pending": "pending",
                ":now": now,
                ":expected": take["takeNumber"],
            },
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            story_instance_takes_table.update_item(
                Key={"takeId": take_id},
                UpdateExpression="SET uploadStatus = :u, alignmentStatus = :s",
                ExpressionAttributeValues={":u": "uploaded", ":s": "superseded"},
            )
            return response(200, {
                "message": "Uploaded, but this page has since changed or been re-recorded — no alignment triggered.",
                "superseded": True,
            })
        raise

    story_instance_takes_table.update_item(
        Key={"takeId": take_id},
        UpdateExpression="SET uploadStatus = :u, alignmentStatus = :s, uploadedAt = :now",
        ExpressionAttributeValues={":u": "uploaded", ":s": "pending", ":now": now},
    )

    page = story_instance_pages_table.get_item(
        Key={"storyInstanceId": story_instance_id, "pageOrder": page_order}
    ).get("Item")

    sqs_client.send_message(
        QueueUrl=ALIGNMENT_QUEUE_URL,
        MessageBody=json.dumps({
            "contentType": "story_instance",
            "takeId": take_id,
            "storyInstanceId": story_instance_id,
            "pageOrder": page_order,
            "narratorId": take["narratorId"],
            "takeNumber": take["takeNumber"],
            "audioKey": take["audioKey"],
            "text": page.get("resolvedText", "") if page else "",
        }),
    )

    return response(200, {"message": "Confirmed, alignment queued.", "takeId": take_id})


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
