from aws_cdk import (
    Duration,
    aws_apigateway as apigw,
    aws_lambda as lambda_,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_sns as sns,
    aws_lambda_event_sources as event_sources,
)
from constructs import Construct


class ApiConstruct(Construct):

    def __init__(
        self,
        scope: Construct,
        id: str,
        user_pool: cognito.UserPool,
        households_table: dynamodb.Table,
        users_table: dynamodb.Table,
        children_table: dynamodb.Table,
        stories_table: dynamodb.Table,
        story_requests_table: dynamodb.Table,
        linked_devices_table: dynamodb.Table,
        audio_bucket: s3.Bucket,
        audio_processing_queue: sqs.Queue,
        story_request_topic: sns.Topic,
        story_ready_topic: sns.Topic,
    ) -> None:
        super().__init__(scope, id)

        # Shared Lambda environment variables
        common_env = {
            "HOUSEHOLDS_TABLE": households_table.table_name,
            "USERS_TABLE": users_table.table_name,
            "CHILDREN_TABLE": children_table.table_name,
            "STORIES_TABLE": stories_table.table_name,
            "STORY_REQUESTS_TABLE": story_requests_table.table_name,
            "LINKED_DEVICES_TABLE": linked_devices_table.table_name,
            "AUDIO_BUCKET": audio_bucket.bucket_name,
            "AUDIO_PROCESSING_QUEUE_URL": audio_processing_queue.queue_url,
            "STORY_REQUEST_TOPIC_ARN": story_request_topic.topic_arn,
            "STORY_READY_TOPIC_ARN": story_ready_topic.topic_arn,
        }

        # --- Lambda Functions ---

        # Households
        self.households_fn = lambda_.Function(
            self, "HouseholdsFn",
            function_name="tuck-me-in-households",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/households"),
            environment=common_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # Stories
        self.stories_fn = lambda_.Function(
            self, "StoriesFn",
            function_name="tuck-me-in-stories",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/stories"),
            environment=common_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # Story Requests
        self.requests_fn = lambda_.Function(
            self, "RequestsFn",
            function_name="tuck-me-in-requests",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/requests"),
            environment=common_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # Devices
        self.devices_fn = lambda_.Function(
            self, "DevicesFn",
            function_name="tuck-me-in-devices",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/devices"),
            environment=common_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # Audio processor (triggered by SQS)
        self.audio_processor_fn = lambda_.Function(
            self, "AudioProcessorFn",
            function_name="tuck-me-in-audio-processor",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/audio_processor"),
            environment=common_env,
            timeout=Duration.minutes(15),
            memory_size=1024,
        )
        self.audio_processor_fn.add_event_source(
            event_sources.SqsEventSource(audio_processing_queue, batch_size=1)
        )

        # --- DynamoDB Permissions ---
        households_table.grant_read_write_data(self.households_fn)
        users_table.grant_read_write_data(self.households_fn)
        children_table.grant_read_write_data(self.households_fn)

        stories_table.grant_read_write_data(self.stories_fn)
        stories_table.grant_read_data(self.requests_fn)
        stories_table.grant_read_write_data(self.audio_processor_fn)

        story_requests_table.grant_read_write_data(self.requests_fn)

        linked_devices_table.grant_read_write_data(self.devices_fn)

        # --- S3 Permissions ---
        audio_bucket.grant_read_write(self.stories_fn)
        audio_bucket.grant_read_write(self.audio_processor_fn)

        # --- SQS Permissions ---
        audio_processing_queue.grant_send_messages(self.stories_fn)

        # --- SNS Permissions ---
        story_request_topic.grant_publish(self.requests_fn)
        story_ready_topic.grant_publish(self.audio_processor_fn)

        # --- API Gateway ---
        self.api = apigw.RestApi(
            self, "TuckMeInApi",
            rest_api_name="Tuck Me In API",
            deploy_options=apigw.StageOptions(stage_name="v1"),
        )

        # Cognito authorizer
        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self, "CognitoAuthorizer",
            cognito_user_pools=[user_pool],
        )
        auth_opts = {
            "authorizer": authorizer,
            "authorization_type": apigw.AuthorizationType.COGNITO,
        }

        def add_auth_method(resource, method, integration):
            resource.add_method(
                method, integration,
                authorizer=authorizer,
                authorization_type=apigw.AuthorizationType.COGNITO,
            )

        # /households
        households_resource = self.api.root.add_resource("households")
        households_resource.add_method("POST", apigw.LambdaIntegration(self.households_fn))
        add_auth_method(households_resource, "GET", apigw.LambdaIntegration(self.households_fn))
        household_by_id = households_resource.add_resource("{householdId}")
        add_auth_method(household_by_id, "GET", apigw.LambdaIntegration(self.households_fn))
        add_auth_method(household_by_id, "PUT", apigw.LambdaIntegration(self.households_fn))

        # /households/{id}/children
        children_resource = household_by_id.add_resource("children")
        add_auth_method(children_resource, "POST", apigw.LambdaIntegration(self.households_fn))
        add_auth_method(children_resource, "GET", apigw.LambdaIntegration(self.households_fn))

        # /stories
        stories_resource = self.api.root.add_resource("stories")
        add_auth_method(stories_resource, "POST", apigw.LambdaIntegration(self.stories_fn))
        add_auth_method(stories_resource, "GET", apigw.LambdaIntegration(self.stories_fn))
        story_by_id = stories_resource.add_resource("{storyId}")
        add_auth_method(story_by_id, "GET", apigw.LambdaIntegration(self.stories_fn))
        add_auth_method(story_by_id, "DELETE", apigw.LambdaIntegration(self.stories_fn))

        # /stories/{id}/upload-url (presigned URL for audio upload)
        upload_url_resource = story_by_id.add_resource("upload-url")
        add_auth_method(upload_url_resource, "GET", apigw.LambdaIntegration(self.stories_fn))

        # /requests
        requests_resource = self.api.root.add_resource("requests")
        add_auth_method(requests_resource, "POST", apigw.LambdaIntegration(self.requests_fn))
        add_auth_method(requests_resource, "GET", apigw.LambdaIntegration(self.requests_fn))
        request_by_id = requests_resource.add_resource("{requestId}")
        add_auth_method(request_by_id, "GET", apigw.LambdaIntegration(self.requests_fn))
        add_auth_method(request_by_id, "PUT", apigw.LambdaIntegration(self.requests_fn))

        # /devices
        devices_resource = self.api.root.add_resource("devices")
        add_auth_method(devices_resource, "POST", apigw.LambdaIntegration(self.devices_fn))
        add_auth_method(devices_resource, "GET", apigw.LambdaIntegration(self.devices_fn))
        device_by_id = devices_resource.add_resource("{deviceId}")
        add_auth_method(device_by_id, "DELETE", apigw.LambdaIntegration(self.devices_fn))
