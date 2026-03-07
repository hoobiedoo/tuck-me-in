import os
import subprocess

from aws_cdk import (
    Duration,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sns as sns,
    CfnOutput,
)
from constructs import Construct

# Pre-bundle: install Alexa SDK dependencies into the lambda directory
_alexa_lambda_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "voice", "alexa", "lambda")
_alexa_lambda_dir = os.path.normpath(_alexa_lambda_dir)
_requirements_file = os.path.join(_alexa_lambda_dir, "requirements.txt")
if os.path.isfile(_requirements_file):
    subprocess.check_call(
        ["pip", "install", "-r", _requirements_file, "-t", _alexa_lambda_dir, "-q", "--upgrade"],
    )


class AlexaSkillConstruct(Construct):

    def __init__(
        self,
        scope: Construct,
        id: str,
        stories_table: dynamodb.Table,
        story_requests_table: dynamodb.Table,
        linked_devices_table: dynamodb.Table,
        users_table: dynamodb.Table,
        children_table: dynamodb.Table,
        audio_bucket: s3.Bucket,
        cloudfront_domain: str,
        story_request_topic: sns.Topic,
    ) -> None:
        super().__init__(scope, id)

        self.alexa_handler = lambda_.Function(
            self, "AlexaSkillFn",
            function_name="tuck-me-in-alexa-skill",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("../voice/alexa/lambda"),
            environment={
                "STORIES_TABLE": stories_table.table_name,
                "STORY_REQUESTS_TABLE": story_requests_table.table_name,
                "LINKED_DEVICES_TABLE": linked_devices_table.table_name,
                "USERS_TABLE": users_table.table_name,
                "CHILDREN_TABLE": children_table.table_name,
                "AUDIO_BUCKET": audio_bucket.bucket_name,
                "CLOUDFRONT_DOMAIN": cloudfront_domain,
                "STORY_REQUEST_TOPIC_ARN": story_request_topic.topic_arn,
            },
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # DynamoDB read permissions
        stories_table.grant_read_data(self.alexa_handler)
        linked_devices_table.grant_read_data(self.alexa_handler)
        users_table.grant_read_data(self.alexa_handler)
        children_table.grant_read_data(self.alexa_handler)

        # Story requests: read + write (to create requests)
        story_requests_table.grant_read_write_data(self.alexa_handler)

        # SNS publish for story request notifications
        story_request_topic.grant_publish(self.alexa_handler)

        # S3 read for audio (though CloudFront is the primary delivery path)
        audio_bucket.grant_read(self.alexa_handler)

        # Allow Alexa service to invoke this Lambda
        self.alexa_handler.add_permission(
            "AlexaSkillInvoke",
            principal=iam.ServicePrincipal("alexa-appkit.amazon.com"),
            action="lambda:InvokeFunction",
        )

        CfnOutput(
            self, "AlexaSkillLambdaArn",
            value=self.alexa_handler.function_arn,
            description="ARN for the Alexa Skill Lambda — use this when configuring the skill endpoint in the Alexa Developer Console",
        )
