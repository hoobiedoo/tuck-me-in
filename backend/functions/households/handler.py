import json
import os
import uuid
import random
import string

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
    elif resource == "/households/join" and http_method == "POST":
        return join_household(event)
    elif resource == "/households/{householdId}" and http_method == "GET":
        return get_household(event)
    elif resource == "/households/{householdId}" and http_method == "PUT":
        return update_household(event)
    elif resource == "/households/{householdId}/invite" and http_method == "POST":
        return generate_invite(event)
    elif resource == "/households/{householdId}/children" and http_method == "POST":
        return create_child(event)
    elif resource == "/households/{householdId}/children" and http_method == "GET":
        return list_children(event)
    elif resource == "/households/{householdId}/members" and http_method == "POST":
        return create_member(event)
    elif resource == "/households/{householdId}/members" and http_method == "GET":
        return list_members(event)
    elif resource == "/households/{householdId}/members/{userId}" and http_method == "PUT":
        return update_member(event)

    return response(404, {"message": "Not found"})


def get_caller_id(event):
    """Extract the Cognito user ID from the request context."""
    try:
        return event["requestContext"]["authorizer"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def create_household(event):
    body = json.loads(event["body"])
    household_id = str(uuid.uuid4())
    invite_code = _generate_code()

    item = {
        "householdId": household_id,
        "name": body["name"],
        "plan": "free",
        "inviteCode": invite_code,
    }
    households_table.put_item(Item=item)
    return response(201, item)


def generate_invite(event):
    """Regenerate the invite code for a household (admin only)."""
    household_id = event["pathParameters"]["householdId"]
    caller_id = get_caller_id(event)

    if not _is_admin(caller_id, household_id):
        return response(403, {"message": "Only the household admin can generate invite codes."})

    new_code = _generate_code()
    households_table.update_item(
        Key={"householdId": household_id},
        UpdateExpression="SET inviteCode = :code",
        ExpressionAttributeValues={":code": new_code},
    )
    return response(200, {"inviteCode": new_code})


def join_household(event):
    """Join an existing household using an invite code."""
    body = json.loads(event["body"])
    invite_code = body.get("inviteCode", "").strip().upper()

    if not invite_code:
        return response(400, {"message": "Invite code is required."})

    # Scan for the household with this invite code
    result = households_table.scan(
        FilterExpression="inviteCode = :code",
        ExpressionAttributeValues={":code": invite_code},
    )
    items = result.get("Items", [])
    if not items:
        return response(404, {"message": "Invalid invite code."})

    household = items[0]
    household_id = household["householdId"]

    # Create user record as member
    user_id = body["userId"]
    existing = users_table.get_item(Key={"userId": user_id}).get("Item")
    if existing and existing.get("householdId") == household_id:
        return response(200, household)

    item = {
        "userId": user_id,
        "householdId": household_id,
        "displayName": body.get("displayName", ""),
        "firstName": body.get("firstName", ""),
        "lastName": body.get("lastName", ""),
        "role": "member",
    }
    users_table.put_item(Item=item)
    return response(200, household)


def list_households(event):
    caller_id = get_caller_id(event)
    if caller_id:
        # Return only households this user belongs to
        user_result = users_table.get_item(Key={"userId": caller_id})
        user = user_result.get("Item")
        if user and user.get("householdId"):
            hh_result = households_table.get_item(Key={"householdId": user["householdId"]})
            hh = hh_result.get("Item")
            if hh:
                return response(200, [hh])
    return response(200, [])


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


def create_member(event):
    household_id = event["pathParameters"]["householdId"]
    body = json.loads(event["body"])

    # Check if this is the first member (they become admin)
    existing_members = users_table.query(
        IndexName="byHousehold",
        KeyConditionExpression="householdId = :hid",
        ExpressionAttributeValues={":hid": household_id},
    )
    is_first = len(existing_members.get("Items", [])) == 0
    role = "admin" if is_first else body.get("role", "member")

    # Don't overwrite an existing member's role
    existing_user = users_table.get_item(Key={"userId": body["userId"]}).get("Item")
    if existing_user and existing_user.get("householdId") == household_id:
        # Already a member, just update non-role fields if needed
        return response(200, existing_user)

    item = {
        "userId": body["userId"],
        "householdId": household_id,
        "displayName": body.get("displayName", ""),
        "firstName": body.get("firstName", ""),
        "lastName": body.get("lastName", ""),
        "role": role,
    }
    users_table.put_item(Item=item)
    return response(201, item)


def list_members(event):
    household_id = event["pathParameters"]["householdId"]
    result = users_table.query(
        IndexName="byHousehold",
        KeyConditionExpression="householdId = :hid",
        ExpressionAttributeValues={":hid": household_id},
    )
    return response(200, result.get("Items", []))


def update_member(event):
    household_id = event["pathParameters"]["householdId"]
    user_id = event["pathParameters"]["userId"]
    body = json.loads(event["body"])

    update_expr = "SET displayName = :dn"
    expr_values = {":dn": body["displayName"]}

    result = users_table.update_item(
        Key={"userId": user_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
        ReturnValues="ALL_NEW",
    )
    return response(200, result["Attributes"])


def list_children(event):
    household_id = event["pathParameters"]["householdId"]
    result = children_table.query(
        IndexName="byHousehold",
        KeyConditionExpression="householdId = :hid",
        ExpressionAttributeValues={":hid": household_id},
    )
    return response(200, result.get("Items", []))


def _generate_code():
    """Generate a 6-character alphanumeric invite code."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _is_admin(user_id, household_id):
    """Check if a user is the admin of a household."""
    if not user_id:
        return False
    result = users_table.get_item(Key={"userId": user_id})
    item = result.get("Item")
    return (
        item
        and item.get("householdId") == household_id
        and item.get("role") == "admin"
    )


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
