import json
import os
import uuid
from datetime import datetime

import boto3

dynamodb = boto3.resource("dynamodb")
story_requests_table = dynamodb.Table(os.environ["STORY_REQUESTS_TABLE"])
sns_client = boto3.client("sns")

STORY_REQUEST_TOPIC_ARN = os.environ["STORY_REQUEST_TOPIC_ARN"]


def lambda_handler(event, context):
    http_method = event["httpMethod"]
    resource = event["resource"]

    if resource == "/requests" and http_method == "POST":
        return create_request(event)
    elif resource == "/requests" and http_method == "GET":
        return list_requests(event)
    elif resource == "/requests/{requestId}" and http_method == "GET":
        return get_request(event)
    elif resource == "/requests/{requestId}" and http_method == "PUT":
        return update_request(event)

    return response(404, {"message": "Not found"})


def create_request(event):
    body = json.loads(event["body"])
    request_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    item = {
        "requestId": request_id,
        "householdId": body["householdId"],
        "childId": body["childId"],
        "requestedReaderId": body["requestedReaderId"],
        "bookTitle": body["bookTitle"],
        "status": "pending",
        "resultingStoryId": None,
        "createdAt": now,
        "updatedAt": now,
    }
    story_requests_table.put_item(Item=item)

    # Notify the requested reader via SNS
    sns_client.publish(
        TopicArn=STORY_REQUEST_TOPIC_ARN,
        Subject="New Story Request",
        Message=json.dumps({
            "requestId": request_id,
            "requestedReaderId": body["requestedReaderId"],
            "childId": body["childId"],
            "bookTitle": body["bookTitle"],
        }),
    )

    return response(201, item)


def list_requests(event):
    params = event.get("queryStringParameters") or {}
    household_id = params.get("householdId")
    reader_id = params.get("requestedReaderId")

    if reader_id:
        result = story_requests_table.query(
            IndexName="byRequestedReader",
            KeyConditionExpression="requestedReaderId = :rid",
            ExpressionAttributeValues={":rid": reader_id},
        )
    elif household_id:
        result = story_requests_table.query(
            IndexName="byHousehold",
            KeyConditionExpression="householdId = :hid",
            ExpressionAttributeValues={":hid": household_id},
        )
    else:
        return response(400, {"message": "householdId or requestedReaderId query parameter required"})

    return response(200, result.get("Items", []))


def get_request(event):
    request_id = event["pathParameters"]["requestId"]
    result = story_requests_table.get_item(Key={"requestId": request_id})
    item = result.get("Item")
    if not item:
        return response(404, {"message": "Request not found"})
    return response(200, item)


def update_request(event):
    request_id = event["pathParameters"]["requestId"]
    body = json.loads(event["body"])
    now = datetime.utcnow().isoformat()

    update_expr = "SET #s = :status, updatedAt = :now"
    expr_names = {"#s": "status"}
    expr_values = {":status": body["status"], ":now": now}

    if "resultingStoryId" in body:
        update_expr += ", resultingStoryId = :storyId"
        expr_values[":storyId"] = body["resultingStoryId"]

    result = story_requests_table.update_item(
        Key={"requestId": request_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
        ReturnValues="ALL_NEW",
    )
    return response(200, result["Attributes"])


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
