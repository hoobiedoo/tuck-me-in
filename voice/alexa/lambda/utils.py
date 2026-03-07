import os
import random

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")

STORIES_TABLE = os.environ.get("STORIES_TABLE", "tuck-me-in-stories")
STORY_REQUESTS_TABLE = os.environ.get("STORY_REQUESTS_TABLE", "tuck-me-in-story-requests")
LINKED_DEVICES_TABLE = os.environ.get("LINKED_DEVICES_TABLE", "tuck-me-in-linked-devices")
USERS_TABLE = os.environ.get("USERS_TABLE", "tuck-me-in-users")
CHILDREN_TABLE = os.environ.get("CHILDREN_TABLE", "tuck-me-in-children")
CLOUDFRONT_DOMAIN = os.environ.get("CLOUDFRONT_DOMAIN", "")
STORY_REQUEST_TOPIC_ARN = os.environ.get("STORY_REQUEST_TOPIC_ARN", "")

stories_table = dynamodb.Table(STORIES_TABLE)
story_requests_table = dynamodb.Table(STORY_REQUESTS_TABLE)
linked_devices_table = dynamodb.Table(LINKED_DEVICES_TABLE)
users_table = dynamodb.Table(USERS_TABLE)
children_table = dynamodb.Table(CHILDREN_TABLE)


def get_household_id_for_device(device_id):
    """Look up the household linked to this Alexa device."""
    result = linked_devices_table.get_item(Key={"deviceId": device_id})
    item = result.get("Item")
    if item:
        return item["householdId"]
    return None


def get_stories_for_household(household_id, reader_name=None):
    """Get all ready stories for a household, optionally filtered by reader display name."""
    result = stories_table.query(
        IndexName="byHousehold",
        KeyConditionExpression=Key("householdId").eq(household_id),
    )
    stories = [s for s in result.get("Items", []) if s.get("status") == "ready"]

    if reader_name:
        reader_name_lower = reader_name.lower()
        # Look up readers in the household to match display name
        users_result = users_table.query(
            IndexName="byHousehold",
            KeyConditionExpression=Key("householdId").eq(household_id),
        )
        reader_id = None
        for user in users_result.get("Items", []):
            if user.get("displayName", "").lower() == reader_name_lower:
                reader_id = user["userId"]
                break
        if reader_id:
            stories = [s for s in stories if s.get("readerId") == reader_id]
        else:
            stories = []

    return stories


def get_story_by_title(household_id, title, reader_name=None):
    """Find a specific story by title (and optionally reader)."""
    stories = get_stories_for_household(household_id, reader_name)
    title_lower = title.lower()
    for story in stories:
        if story.get("title", "").lower() == title_lower:
            return story
    # Fuzzy match: check if title is contained in story title
    for story in stories:
        if title_lower in story.get("title", "").lower():
            return story
    return None


def get_random_story(household_id, reader_name=None):
    """Pick a random ready story from the household library."""
    stories = get_stories_for_household(household_id, reader_name)
    if stories:
        return random.choice(stories)
    return None


def get_audio_url(audio_key):
    """Build the CloudFront URL for an audio file."""
    if CLOUDFRONT_DOMAIN:
        return f"https://{CLOUDFRONT_DOMAIN}/{audio_key}"
    return None


def get_reader_display_name(reader_id):
    """Get the display name for a reader."""
    result = users_table.get_item(Key={"userId": reader_id})
    item = result.get("Item")
    if item:
        return item.get("displayName", "someone")
    return "someone"


def create_story_request(household_id, reader_name, book_title):
    """Create a story request and notify the reader via SNS."""
    import uuid
    from datetime import datetime

    # Find the reader by display name
    users_result = users_table.query(
        IndexName="byHousehold",
        KeyConditionExpression=Key("householdId").eq(household_id),
    )
    reader_id = None
    for user in users_result.get("Items", []):
        if user.get("displayName", "").lower() == reader_name.lower():
            reader_id = user["userId"]
            break

    if not reader_id:
        return None

    # Get first child in household for the request
    children_result = children_table.query(
        IndexName="byHousehold",
        KeyConditionExpression=Key("householdId").eq(household_id),
    )
    children = children_result.get("Items", [])
    child_id = children[0]["childId"] if children else "unknown"

    request_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    item = {
        "requestId": request_id,
        "householdId": household_id,
        "childId": child_id,
        "requestedReaderId": reader_id,
        "bookTitle": book_title,
        "status": "pending",
        "resultingStoryId": None,
        "createdAt": now,
        "updatedAt": now,
    }
    story_requests_table.put_item(Item=item)

    # Send SNS notification
    if STORY_REQUEST_TOPIC_ARN:
        import json
        sns_client = boto3.client("sns")
        sns_client.publish(
            TopicArn=STORY_REQUEST_TOPIC_ARN,
            Subject="New Story Request",
            Message=json.dumps({
                "requestId": request_id,
                "requestedReaderId": reader_id,
                "childId": child_id,
                "bookTitle": book_title,
            }),
        )

    return item
