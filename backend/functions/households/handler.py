import json
import os
import uuid

import boto3

dynamodb = boto3.resource("dynamodb")
households_table = dynamodb.Table(os.environ["HOUSEHOLDS_TABLE"])
users_table = dynamodb.Table(os.environ["USERS_TABLE"])
children_table = dynamodb.Table(os.environ["CHILDREN_TABLE"])


def lambda_handler(event, context):
    http_method = event["httpMethod"]
    resource = event["resource"]

    if resource == "/households" and http_method == "POST":
        return create_household(event)
    elif resource == "/households" and http_method == "GET":
        return list_households(event)
    elif resource == "/households/{householdId}" and http_method == "GET":
        return get_household(event)
    elif resource == "/households/{householdId}" and http_method == "PUT":
        return update_household(event)
    elif resource == "/households/{householdId}/children" and http_method == "POST":
        return create_child(event)
    elif resource == "/households/{householdId}/children" and http_method == "GET":
        return list_children(event)

    return response(404, {"message": "Not found"})


def create_household(event):
    body = json.loads(event["body"])
    household_id = str(uuid.uuid4())

    item = {
        "householdId": household_id,
        "name": body["name"],
        "plan": "free",
    }
    households_table.put_item(Item=item)
    return response(201, item)


def list_households(event):
    # Users can only list their own household (filtered by claims in production)
    result = households_table.scan()
    return response(200, result.get("Items", []))


def get_household(event):
    household_id = event["pathParameters"]["householdId"]
    result = households_table.get_item(Key={"householdId": household_id})
    item = result.get("Item")
    if not item:
        return response(404, {"message": "Household not found"})
    return response(200, item)


def update_household(event):
    household_id = event["pathParameters"]["householdId"]
    body = json.loads(event["body"])

    update_expr = "SET #n = :name"
    expr_names = {"#n": "name"}
    expr_values = {":name": body["name"]}

    if "plan" in body:
        update_expr += ", #p = :plan"
        expr_names["#p"] = "plan"
        expr_values[":plan"] = body["plan"]

    result = households_table.update_item(
        Key={"householdId": household_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
        ReturnValues="ALL_NEW",
    )
    return response(200, result["Attributes"])


def create_child(event):
    household_id = event["pathParameters"]["householdId"]
    body = json.loads(event["body"])
    child_id = str(uuid.uuid4())

    item = {
        "childId": child_id,
        "householdId": household_id,
        "name": body["name"],
        "approvedReaders": body.get("approvedReaders", []),
    }
    children_table.put_item(Item=item)
    return response(201, item)


def list_children(event):
    household_id = event["pathParameters"]["householdId"]
    result = children_table.query(
        IndexName="byHousehold",
        KeyConditionExpression="householdId = :hid",
        ExpressionAttributeValues={":hid": household_id},
    )
    return response(200, result.get("Items", []))


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
