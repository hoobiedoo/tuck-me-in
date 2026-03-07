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
    for record in event["Records"]:
        message = json.loads(record["body"])
        process_audio(message)


def process_audio(message):
    story_id = message["storyId"]
    audio_key = message["audioKey"]

    # Update status to processing
    stories_table.update_item(
        Key={"storyId": story_id},
        UpdateExpression="SET #s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "processing"},
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
                "householdId": message.get("householdId"),
                "title": message.get("title"),
            }),
        )

    except Exception as e:
        stories_table.update_item(
            Key={"storyId": story_id},
            UpdateExpression="SET #s = :status",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":status": "failed"},
        )
        raise e
