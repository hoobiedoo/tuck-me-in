import json
import os
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
takes_table = dynamodb.Table(os.environ["TAKES_TABLE"])
segment_recordings_table = dynamodb.Table(os.environ["SEGMENT_RECORDINGS_TABLE"])
story_instance_takes_table = dynamodb.Table(os.environ["STORY_INSTANCE_TAKES_TABLE"])
story_instance_segment_recordings_table = dynamodb.Table(os.environ["STORY_INSTANCE_SEGMENT_RECORDINGS_TABLE"])
s3_client = boto3.client("s3")

AUDIO_BUCKET = os.environ["AUDIO_BUCKET"]


def lambda_handler(event, context):
    failed_items = []

    for record in event["Records"]:
        try:
            message = json.loads(record["body"])
            # Books messages predate contentType and never carry it —
            # default keeps every existing message routing exactly where
            # it always has.
            if message.get("contentType", "book") == "story_instance":
                process_story_instance_alignment(message)
            else:
                process_book_alignment(message)
        except Exception as e:
            print(f"Failed to align take: {e}")
            failed_items.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": failed_items}


def process_book_alignment(message):
    take_id = message["takeId"]
    book_id = message["bookId"]
    cfi = message["cfi"]
    contributor_id = message["contributorId"]
    take_number = message["takeNumber"]
    audio_key = message["audioKey"]
    text = message["text"]

    alignment_data = _run_forced_alignment_or_mark_failed(takes_table, take_id, audio_key, text)
    if alignment_data is None:
        return

    contributor_segment_key = f"{contributor_id}#{cfi}"
    _write_alignment_result(
        takes_table, segment_recordings_table, take_id, alignment_data, take_number,
        segment_key={"bookId": book_id, "contributorSegmentKey": contributor_segment_key},
    )


def process_story_instance_alignment(message):
    """Same job, same version guard, targeting the StoryInstance-scoped
    mirror tables instead — see the design proposal §6 for why these are
    separate tables rather than an overloaded contentType branch inside
    Books' own tables: different content classification, different
    readiness gate. The alignment logic itself doesn't care, so it's
    shared here rather than duplicated into a second Lambda."""
    take_id = message["takeId"]
    story_instance_id = message["storyInstanceId"]
    page_order = message["pageOrder"]
    take_number = message["takeNumber"]
    audio_key = message["audioKey"]
    text = message["text"]

    alignment_data = _run_forced_alignment_or_mark_failed(story_instance_takes_table, take_id, audio_key, text)
    if alignment_data is None:
        return

    _write_alignment_result(
        story_instance_takes_table, story_instance_segment_recordings_table, take_id, alignment_data, take_number,
        segment_key={"storyInstanceId": story_instance_id, "pageOrder": page_order},
    )


def _run_forced_alignment_or_mark_failed(takes_tbl, take_id, audio_key, text):
    takes_tbl.update_item(
        Key={"takeId": take_id},
        UpdateExpression="SET alignmentStatus = :s",
        ExpressionAttributeValues={":s": "processing"},
    )
    try:
        return _run_forced_alignment(audio_key, text)
    except Exception as e:
        takes_tbl.update_item(
            Key={"takeId": take_id},
            UpdateExpression="SET alignmentStatus = :s, alignmentError = :e",
            ExpressionAttributeValues={":s": "failed", ":e": str(e)[:500]},
        )
        raise  # genuine failure — let SQS retry, eventually DLQ after 3 attempts


def _write_alignment_result(takes_tbl, segment_recordings_tbl, take_id, alignment_data, take_number, segment_key):
    now = datetime.utcnow().isoformat()
    try:
        # The version guard: only accept this result if no newer take has
        # superseded it since this job was enqueued (a real newer
        # recording, or the underlying text changing under this one — see
        # write_slots' supersede-on-edit). Atomic conditional write, not a
        # read-then-check — closes the race window entirely rather than
        # just narrowing it.
        segment_recordings_tbl.update_item(
            Key=segment_key,
            UpdateExpression="SET alignmentStatus = :s, alignmentData = :data, updatedAt = :now",
            ConditionExpression="currentTakeNumber = :expected",
            ExpressionAttributeValues={
                ":s": "complete",
                ":data": alignment_data,
                ":now": now,
                ":expected": take_number,
            },
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Not a failure — a newer take already exists, or a slot edit
            # superseded this one, so this result is correctly obsolete.
            # Don't retry; whatever now owns currentTakeId is what will
            # produce (or already produced) the current data. Still record
            # the outcome on this take's own independent row for an honest
            # audit trail.
            takes_tbl.update_item(
                Key={"takeId": take_id},
                UpdateExpression="SET alignmentStatus = :s",
                ExpressionAttributeValues={":s": "superseded"},
            )
            print(f"Take {take_id} (v{take_number}) superseded before alignment could be applied — discarding, not retrying.")
            return
        raise

    takes_tbl.update_item(
        Key={"takeId": take_id},
        UpdateExpression="SET alignmentStatus = :s, alignmentData = :data",
        ExpressionAttributeValues={":s": "complete", ":data": alignment_data},
    )


def _run_forced_alignment(audio_key, text):
    """Not yet implemented — the forced-alignment engine/service hasn't
    been chosen. This is the one placeholder in this Lambda; everything
    around it (queueing, versioning, the race guard) is real and wired.

    Candidates: a self-hosted aligner (e.g. Gentle, aeneas) run in this
    Lambda or a container, or a managed STT service's word-timestamp
    feature. Whichever is picked, this function's contract stays the same:
    given an S3 audio key and the segment's known text, return
    [{"word": str, "startMs": int, "endMs": int}, ...] covering the clip.
    """
    raise NotImplementedError(
        "Forced alignment engine not yet selected — see this function's docstring."
    )
