import json
import os
import time
import uuid

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
            "generate_illustration_spec", "generate_illustrations",
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


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
