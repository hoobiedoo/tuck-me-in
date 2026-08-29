import json
import os

import boto3

dynamodb = boto3.resource("dynamodb")
pending_notifications_table = dynamodb.Table(os.environ["PENDING_PUBLISH_NOTIFICATIONS_TABLE"])
users_table = dynamodb.Table(os.environ["USERS_TABLE"])
sns_client = boto3.client("sns")

PUBLISH_DIGEST_TOPIC_ARN = os.environ["PUBLISH_DIGEST_TOPIC_ARN"]


def lambda_handler(event, context):
    """Runs on a fixed schedule. Drains every open publish-notification window
    and sends one summary notification per household, rather than one per
    recording that was published."""
    windows = pending_notifications_table.scan().get("Items", [])

    for window in windows:
        send_digest(window)
        pending_notifications_table.delete_item(
            Key={
                "householdId": window["householdId"],
                "windowStartedAt": window["windowStartedAt"],
            }
        )


def send_digest(window):
    household_id = window["householdId"]
    recording_ids = window.get("recordingIds", [])
    if not recording_ids:
        return

    admins = users_table.query(
        IndexName="byHousehold",
        KeyConditionExpression="householdId = :hid",
        ExpressionAttributeValues={":hid": household_id},
    ).get("Items", [])
    parent_user_ids = [u["userId"] for u in admins if u.get("role") == "admin"]
    if not parent_user_ids:
        return

    count = len(recording_ids)
    subject = "New recordings ready to review" if count > 1 else "New recording ready to review"
    message = (
        f"{count} new recording{'s' if count != 1 else ''} ready for you to review and release."
    )

    sns_client.publish(
        TopicArn=PUBLISH_DIGEST_TOPIC_ARN,
        Subject=subject,
        Message=json.dumps({
            "householdId": household_id,
            "parentUserIds": parent_user_ids,
            "recordingIds": recording_ids,
            "message": message,
        }),
    )
