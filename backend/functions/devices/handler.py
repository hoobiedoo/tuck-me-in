import json
import os
import uuid
from datetime import datetime

import boto3

dynamodb = boto3.resource("dynamodb")
linked_devices_table = dynamodb.Table(os.environ["LINKED_DEVICES_TABLE"])


def lambda_handler(event, context):
    http_method = event["httpMethod"]
    resource = event["resource"]

    if resource == "/devices" and http_method == "POST":
        return link_device(event)
    elif resource == "/devices" and http_method == "GET":
        return list_devices(event)
    elif resource == "/devices/{deviceId}" and http_method == "DELETE":
        return unlink_device(event)

    return response(404, {"message": "Not found"})


def link_device(event):
    body = json.loads(event["body"])

    item = {
        "deviceId": body["deviceId"],
        "householdId": body["householdId"],
        "platform": body["platform"],
        "linkedAt": datetime.utcnow().isoformat(),
    }
    linked_devices_table.put_item(Item=item)
    return response(201, item)


def list_devices(event):
    params = event.get("queryStringParameters") or {}
    household_id = params.get("householdId")

    if not household_id:
        return response(400, {"message": "householdId query parameter required"})

    result = linked_devices_table.query(
        IndexName="byHousehold",
        KeyConditionExpression="householdId = :hid",
        ExpressionAttributeValues={":hid": household_id},
    )
    return response(200, result.get("Items", []))


def unlink_device(event):
    device_id = event["pathParameters"]["deviceId"]
    linked_devices_table.delete_item(Key={"deviceId": device_id})
    return response(200, {"message": "Device unlinked"})


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
