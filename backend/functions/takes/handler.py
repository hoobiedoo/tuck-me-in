import json
import os
import uuid
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
takes_table = dynamodb.Table(os.environ["TAKES_TABLE"])
segment_recordings_table = dynamodb.Table(os.environ["SEGMENT_RECORDINGS_TABLE"])
books_table = dynamodb.Table(os.environ["BOOKS_TABLE"])
book_segments_table = dynamodb.Table(os.environ["BOOK_SEGMENTS_TABLE"])
users_table = dynamodb.Table(os.environ["USERS_TABLE"])
s3_client = boto3.client("s3")
sqs_client = boto3.client("sqs")

AUDIO_BUCKET = os.environ["AUDIO_BUCKET"]
ALIGNMENT_QUEUE_URL = os.environ["ALIGNMENT_QUEUE_URL"]


def lambda_handler(event, context):
    http_method = event["httpMethod"]
    resource = event["resource"]

    if resource == "/takes" and http_method == "POST":
        return begin_take(event)
    elif resource == "/takes/{takeId}/confirm" and http_method == "POST":
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
    """Contributor starts uploading a new recording attempt for a segment.
    Server assigns the take version atomically — the client never
    generates or proposes its own version number, which is what makes the
    later race guard sound (two concurrent begin-take calls for the same
    slot can never produce the same number)."""
    caller_id = _get_caller_id(event)
    household_id = _get_household_id(caller_id)
    if not caller_id or not household_id:
        return response(403, {"message": "Must be an authenticated household member to record."})

    body = json.loads(event["body"])
    book_id = body.get("bookId")
    cfi = body.get("cfi")
    if not book_id or not cfi:
        return response(400, {"message": "bookId and cfi are required."})

    book = books_table.get_item(Key={"bookId": book_id}).get("Item")
    if not book or book.get("catalogueStatus") != "published":
        return response(404, {"message": "Book not found or not published."})

    segments = book_segments_table.query(
        IndexName="byCfi",
        KeyConditionExpression="bookId = :bid AND cfi = :cfi",
        ExpressionAttributeValues={":bid": book_id, ":cfi": cfi},
    ).get("Items", [])
    if not segments or not segments[0].get("narratable"):
        return response(400, {"message": "This segment cannot be recorded (not narratable, or doesn't exist)."})

    contributor_segment_key = f"{caller_id}#{cfi}"
    now = datetime.utcnow().isoformat()

    updated = segment_recordings_table.update_item(
        Key={"bookId": book_id, "contributorSegmentKey": contributor_segment_key},
        UpdateExpression=(
            "ADD currentTakeNumber :one "
            "SET contributorId = :cid, cfi = :cfi, householdId = :hid, "
            "uploadStatus = :uploading, alignmentStatus = :notUploaded, "
            "alignmentData = :none, updatedAt = :now"
        ),
        ExpressionAttributeValues={
            ":one": 1,
            ":cid": caller_id,
            ":cfi": cfi,
            ":hid": household_id,
            ":uploading": "uploading",
            ":notUploaded": "not_uploaded",
            ":none": None,
            ":now": now,
        },
        ReturnValues="ALL_NEW",
    )["Attributes"]

    take_number = int(updated["currentTakeNumber"])
    take_id = str(uuid.uuid4())
    audio_key = f"audio-takes/{book_id}/{caller_id}/{take_id}.mp3"

    takes_table.put_item(Item={
        "takeId": take_id,
        "segmentSlotKey": f"{book_id}#{cfi}#{caller_id}",
        "takeNumber": take_number,
        "bookId": book_id,
        "cfi": cfi,
        "contributorId": caller_id,
        "householdId": household_id,
        "audioKey": audio_key,
        "uploadStatus": "local_only",
        "alignmentStatus": "not_uploaded",
        "recordedAt": now,
    })

    segment_recordings_table.update_item(
        Key={"bookId": book_id, "contributorSegmentKey": contributor_segment_key},
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
    """Client finished PUTting the audio. Marks the take uploaded and
    enqueues alignment — but only if this take is still current. A newer
    take may have already superseded it while this upload was in flight;
    if so, skip enqueueing alignment for audio nobody wants aligned. This
    is a defense-in-depth check, not the only guard — the
    alignment_processor's own conditional write is what's authoritative if
    a race slips past this one (e.g. this check passes, then a new take
    starts before the alignment job finishes)."""
    take_id = event["pathParameters"]["takeId"]
    caller_id = _get_caller_id(event)

    take = takes_table.get_item(Key={"takeId": take_id}).get("Item")
    if not take:
        return response(404, {"message": "Take not found"})
    if take.get("contributorId") != caller_id:
        return response(403, {"message": "Not your take."})

    try:
        s3_client.head_object(Bucket=AUDIO_BUCKET, Key=take["audioKey"])
    except ClientError:
        return response(400, {"message": "Upload not found — PUT the audio before confirming."})

    contributor_segment_key = f"{take['contributorId']}#{take['cfi']}"
    now = datetime.utcnow().isoformat()

    try:
        segment_recordings_table.update_item(
            Key={"bookId": take["bookId"], "contributorSegmentKey": contributor_segment_key},
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
            takes_table.update_item(
                Key={"takeId": take_id},
                UpdateExpression="SET uploadStatus = :u, alignmentStatus = :s",
                ExpressionAttributeValues={":u": "uploaded", ":s": "superseded"},
            )
            return response(200, {
                "message": "Uploaded, but a newer take has since superseded this one — no alignment triggered.",
                "superseded": True,
            })
        raise

    takes_table.update_item(
        Key={"takeId": take_id},
        UpdateExpression="SET uploadStatus = :u, alignmentStatus = :s, uploadedAt = :now",
        ExpressionAttributeValues={":u": "uploaded", ":s": "pending", ":now": now},
    )

    segment = book_segments_table.query(
        IndexName="byCfi",
        KeyConditionExpression="bookId = :bid AND cfi = :cfi",
        ExpressionAttributeValues={":bid": take["bookId"], ":cfi": take["cfi"]},
    )["Items"][0]

    sqs_client.send_message(
        QueueUrl=ALIGNMENT_QUEUE_URL,
        MessageBody=json.dumps({
            "takeId": take_id,
            "bookId": take["bookId"],
            "cfi": take["cfi"],
            "contributorId": take["contributorId"],
            "takeNumber": take["takeNumber"],
            "audioKey": take["audioKey"],
            "text": segment["text"],
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
