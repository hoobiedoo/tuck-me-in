import json
import os
import uuid
from datetime import datetime

import boto3

dynamodb = boto3.resource("dynamodb")
stories_table = dynamodb.Table(os.environ["STORIES_TABLE"])
users_table = dynamodb.Table(os.environ["USERS_TABLE"])
s3_client = boto3.client("s3")
sqs_client = boto3.client("sqs")

AUDIO_BUCKET = os.environ["AUDIO_BUCKET"]
AUDIO_PROCESSING_QUEUE_URL = os.environ["AUDIO_PROCESSING_QUEUE_URL"]
MAX_DURATION_SECONDS = 3600  # 1 hour


def lambda_handler(event, context):
    http_method = event["httpMethod"]
    resource = event["resource"]

    if resource == "/stories" and http_method == "POST":
        return create_story(event)
    elif resource == "/stories" and http_method == "GET":
        return list_stories(event)
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

    return response(404, {"message": "Not found"})


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

    # Only return ready stories for listing
    items = [i for i in result.get("Items", []) if i.get("status") == "ready"]
    return response(200, items)


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
    try:
        head = s3_client.head_object(Bucket=AUDIO_BUCKET, Key=item["audioKey"])
        content_length = head["ContentLength"]

        # Estimate duration from file size (128kbps MP3 ~ 16KB/sec)
        estimated_duration = int(content_length / 16000)

        if estimated_duration > MAX_DURATION_SECONDS:
            stories_table.update_item(
                Key={"storyId": story_id},
                UpdateExpression="SET #s = :status",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":status": "rejected_too_long"},
            )
            return response(400, {
                "message": f"Story exceeds maximum duration of {MAX_DURATION_SECONDS // 60} minutes",
                "estimatedDuration": estimated_duration,
                "maxDuration": MAX_DURATION_SECONDS
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


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
