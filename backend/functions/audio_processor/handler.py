import json
import os

import boto3

dynamodb = boto3.resource("dynamodb")
stories_table = dynamodb.Table(os.environ["STORIES_TABLE"])
s3_client = boto3.client("s3")
sns_client = boto3.client("sns")

AUDIO_BUCKET = os.environ["AUDIO_BUCKET"]
STORY_READY_TOPIC_ARN = os.environ["STORY_READY_TOPIC_ARN"]
MAX_DURATION_SECONDS = 3600  # 1 hour


def lambda_handler(event, context):
    failed_items = []

    for record in event["Records"]:
        try:
            message = json.loads(record["body"])
            # Add receive count to message for retry tracking
            message["ApproximateReceiveCount"] = record["attributes"].get("ApproximateReceiveCount", "1")
            process_audio(message)
        except Exception as e:
            # Log error
            story_id = message.get("storyId", "unknown")
            print(f"Failed to process story {story_id}: {e}")

            # Track failure for SQS (will retry only this message)
            failed_items.append({
                "itemIdentifier": record["messageId"]
            })

    # Return partial batch failures (SQS will retry only failed messages)
    return {
        "batchItemFailures": failed_items
    }


def process_audio(message):
    story_id = message["storyId"]
    audio_key = message["audioKey"]
    household_id = message["householdId"]
    title = message["title"]

    # Track retry attempt
    receive_count = int(message.get("ApproximateReceiveCount", 1))

    # Update status to processing with retry attempt number
    stories_table.update_item(
        Key={"storyId": story_id},
        UpdateExpression="SET #s = :status, retryAttempt = :attempt",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": f"processing_attempt_{receive_count}",
            ":attempt": receive_count,
        },
    )

    try:
        # Get audio file metadata
        head = s3_client.head_object(Bucket=AUDIO_BUCKET, Key=audio_key)
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
            return

        # TODO: Add audio normalization and format conversion here
        # e.g., invoke MediaConvert or process with FFmpeg Lambda layer

        # Update story as ready
        stories_table.update_item(
            Key={"storyId": story_id},
            UpdateExpression="SET #s = :status, durationSeconds = :dur",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": "ready",
                ":dur": estimated_duration,
            },
        )

        # Notify that the story is ready
        sns_client.publish(
            TopicArn=STORY_READY_TOPIC_ARN,
            Subject="Story Ready",
            Message=json.dumps({
                "storyId": story_id,
                "householdId": household_id,
                "title": title,
            }),
        )

    except Exception as e:
        receive_count = int(message.get("ApproximateReceiveCount", 1))

        # If this is the final attempt (3rd try), mark as permanently failed
        if receive_count >= 3:
            status = "failed"
        else:
            status = f"retry_{receive_count}_failed"

        stories_table.update_item(
            Key={"storyId": story_id},
            UpdateExpression="SET #s = :status, retryAttempt = :attempt, lastError = :error",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":attempt": receive_count,
                ":error": str(e)[:500],  # Truncate error to 500 chars
            },
        )
        raise e
