"""Renders a StoryTemplate as a browsable HTML preview by invoking the
story_preview Lambda directly — no API Gateway involved, since this is
internal-only tooling gated purely by your own IAM credentials (the same
way every other script in this directory works).

Usage:
    AWS_REGION=us-east-1 python preview_story_template.py <storyTemplateId> [output.html] [castMemberId] [styleId]

Opens the result in your default browser automatically.
"""

import json
import os
import sys
import webbrowser

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python preview_story_template.py <storyTemplateId> "
            "[output.html] [castMemberId] [styleId]"
        )

    story_template_id = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "preview.html"

    payload = {"storyTemplateId": story_template_id}
    if len(sys.argv) > 3:
        payload["castMemberId"] = sys.argv[3]
    if len(sys.argv) > 4:
        payload["styleId"] = sys.argv[4]

    lambda_client = boto3.client("lambda", region_name=REGION)
    response = lambda_client.invoke(
        FunctionName="tuck-me-in-story-preview",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    html = json.loads(response["Payload"].read())

    with open(output_path, "w") as f:
        f.write(html)

    abs_path = os.path.abspath(output_path)
    print(f"Preview written to {abs_path}")
    webbrowser.open(f"file://{abs_path}")


if __name__ == "__main__":
    main()
