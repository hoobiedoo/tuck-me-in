import json
import os
import time
import uuid
from decimal import Decimal

import boto3


dynamodb = boto3.resource("dynamodb")
jobs_table = dynamodb.Table(os.environ["STORY_PRODUCTION_JOBS_TABLE"])
lambda_client = boto3.client("lambda")
worker_name = os.environ["STORY_PRODUCTION_FUNCTION_NAME"]


def lambda_handler(event, context):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    groups = claims.get("cognito:groups", "")
    if "content-producers" not in [group.strip() for group in groups.split(",")]:
        return response(403, {"message": "Content producer access is required."})
    user_id = claims.get("sub")
    method = event.get("httpMethod")
    resource = event.get("resource")

    if method == "POST" and resource == "/story-production":
        body = json.loads(event.get("body") or "{}")
        action = body.get("action")
        allowed_actions = {
            "generate_concepts", "generate_story", "write_draft",
            "generate_illustration_spec", "generate_illustrations", "write_illustrations",
            "generate_one_illustration",
            # compose*/compose_illustration_spec: no model call, just returns
            # the assembled prompt for manual testing outside this pipeline
            # (e.g. pasted into a plain chat UI) -- lets prompt changes be
            # validated without spending Bedrock tokens through the app.
            "compose_concepts", "compose", "compose_illustration_spec",
            # New interactive content model (entityChoices/branchPoints,
            # see docs/interactive-story-content-model.md) -- experimental,
            # parallel to generate_story; nothing downstream consumes its
            # output yet.
            "compose_interactive_story", "generate_interactive_story",
            "write_interactive_draft",
        }
        if action not in allowed_actions:
            return response(400, {"message": f"action must be one of: {', '.join(sorted(allowed_actions))}."})
        job_id = str(uuid.uuid4())
        now = int(time.time())
        jobs_table.put_item(Item={
            "jobId": job_id, "requestedBy": user_id, "action": action,
            "status": "queued", "createdAt": now, "expiresAt": now + 86400,
        })
        lambda_client.invoke(
            FunctionName=worker_name,
            InvocationType="Event",
            # _requestedBy lets generate_illustrations propagate the same
            # owner onto the child jobs it fans out, so GET below can find them.
            Payload=json.dumps({**body, "_jobId": job_id, "_requestedBy": user_id}).encode(),
        )
        return response(202, {"jobId": job_id, "status": "queued"})

    if method == "GET" and resource == "/story-production/{jobId}":
        job = jobs_table.get_item(Key={"jobId": event["pathParameters"]["jobId"]}).get("Item")
        if not job or job.get("requestedBy") != user_id:
            return response(404, {"message": "Generation job not found."})
        return response(200, job)

    return response(404, {"message": "Not found"})


def _json_default(value):
    if isinstance(value, Decimal):
        # boto3's DynamoDB resource layer deserializes every Number as
        # Decimal, which json.dumps can't serialize -- falling back to
        # str() here (as this used to) turns every numeric field in every
        # job result into a JSON string instead of a number. Confirmed
        # live: a spec's real falloff/opacity floats came back from GET as
        # "2.2"/"0.55" strings, which the client then resent unchanged for
        # rendering and crashed deep in procedural_effects.py.
        as_int = int(value)
        return as_int if as_int == value else float(value)
    return str(value)


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=_json_default),
    }
