import os

from aws_cdk import (
    Aws,
    BundlingOptions,
    Duration,
    aws_apigateway as apigw,
    aws_lambda as lambda_,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_sns as sns,
    aws_events as events,
    aws_events_targets as event_targets,
    aws_iam as iam,
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
        auto_release_grants_table: dynamodb.Table,
        pending_publish_notifications_table: dynamodb.Table,
        books_table: dynamodb.Table,
        book_segments_table: dynamodb.Table,
        book_imports_table: dynamodb.Table,
        takes_table: dynamodb.Table,
        segment_recordings_table: dynamodb.Table,
        theme_packs_table: dynamodb.Table,
        assets_table: dynamodb.Table,
        story_templates_table: dynamodb.Table,
        story_template_pages_table: dynamodb.Table,
        preset_cast_members_table: dynamodb.Table,
        developmental_frameworks_table: dynamodb.Table,
        story_production_jobs_table: dynamodb.Table,
        story_instances_table: dynamodb.Table,
        story_instance_pages_table: dynamodb.Table,
        story_instance_takes_table: dynamodb.Table,
        story_instance_segment_recordings_table: dynamodb.Table,
        audio_bucket: s3.Bucket,
        cdn_domain: str,
        catalogue_source_bucket: s3.Bucket,
        catalogue_assets_bucket: s3.Bucket,
        audio_processing_queue: sqs.Queue,
        book_ingestion_queue: sqs.Queue,
        alignment_queue: sqs.Queue,
        story_request_topic: sns.Topic,
        story_ready_topic: sns.Topic,
        publish_digest_topic: sns.Topic,
        recording_withdrawn_topic: sns.Topic,
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
            "AUTO_RELEASE_GRANTS_TABLE": auto_release_grants_table.table_name,
            "PENDING_PUBLISH_NOTIFICATIONS_TABLE": pending_publish_notifications_table.table_name,
            "BOOKS_TABLE": books_table.table_name,
            "BOOK_SEGMENTS_TABLE": book_segments_table.table_name,
            "BOOK_IMPORTS_TABLE": book_imports_table.table_name,
            "TAKES_TABLE": takes_table.table_name,
            "SEGMENT_RECORDINGS_TABLE": segment_recordings_table.table_name,
            "THEME_PACKS_TABLE": theme_packs_table.table_name,
            "ASSETS_TABLE": assets_table.table_name,
            "STORY_TEMPLATES_TABLE": story_templates_table.table_name,
            "STORY_TEMPLATE_PAGES_TABLE": story_template_pages_table.table_name,
            "PRESET_CAST_MEMBERS_TABLE": preset_cast_members_table.table_name,
            "DEVELOPMENTAL_FRAMEWORKS_TABLE": developmental_frameworks_table.table_name,
            "STORY_INSTANCES_TABLE": story_instances_table.table_name,
            "STORY_INSTANCE_PAGES_TABLE": story_instance_pages_table.table_name,
            "STORY_INSTANCE_TAKES_TABLE": story_instance_takes_table.table_name,
            "STORY_INSTANCE_SEGMENT_RECORDINGS_TABLE": story_instance_segment_recordings_table.table_name,
            "AUDIO_BUCKET": audio_bucket.bucket_name,
            "CDN_DOMAIN": cdn_domain,
            "CATALOGUE_ASSETS_BUCKET": catalogue_assets_bucket.bucket_name,
            "AUDIO_PROCESSING_QUEUE_URL": audio_processing_queue.queue_url,
            "ALIGNMENT_QUEUE_URL": alignment_queue.queue_url,
            "STORY_REQUEST_TOPIC_ARN": story_request_topic.topic_arn,
            "STORY_READY_TOPIC_ARN": story_ready_topic.topic_arn,
            "PUBLISH_DIGEST_TOPIC_ARN": publish_digest_topic.topic_arn,
            "RECORDING_WITHDRAWN_TOPIC_ARN": recording_withdrawn_topic.topic_arn,
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
            timeout=Duration.seconds(60),
            memory_size=1024,
        )
        self.audio_processor_fn.add_event_source(
            event_sources.SqsEventSource(
                audio_processing_queue,
                batch_size=1,
                report_batch_item_failures=True,
            )
        )

        # Publish digest (scheduled — drains PendingPublishNotifications windows)
        self.publish_digest_fn = lambda_.Function(
            self, "PublishDigestFn",
            function_name="tuck-me-in-publish-digest",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/publish_digest"),
            environment=common_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )
        events.Rule(
            self, "PublishDigestSchedule",
            schedule=events.Schedule.rate(Duration.minutes(5)),
            targets=[event_targets.LambdaFunction(self.publish_digest_fn)],
        )

        # Book ingestion (triggered by SQS, fed directly by an S3 event
        # notification on CatalogueSourceBucket — no API Gateway route).
        # Needs ebooklib/lxml, unlike every other function here which only
        # uses boto3 — bundled via Docker at synth/deploy time since those
        # aren't in the Lambda runtime.
        prebundled_book_ingestion = os.environ.get("BOOK_INGESTION_PREBUNDLED_PATH")
        book_ingestion_code = (
            lambda_.Code.from_asset(prebundled_book_ingestion)
            if prebundled_book_ingestion
            else lambda_.Code.from_asset(
                "functions/book_ingestion",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            )
        )
        self.book_ingestion_fn = lambda_.Function(
            self, "BookIngestionFn",
            function_name="tuck-me-in-book-ingestion",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=book_ingestion_code,
            environment=common_env,
            timeout=Duration.seconds(180),
            memory_size=1024,
        )
        self.book_ingestion_fn.add_event_source(
            event_sources.SqsEventSource(
                book_ingestion_queue,
                batch_size=1,
                report_batch_item_failures=True,
            )
        )

        # Books (read-only catalogue browsing — global, not household-scoped)
        self.books_fn = lambda_.Function(
            self, "BooksFn",
            function_name="tuck-me-in-books",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/books"),
            environment=common_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # Takes (contributor begins/confirms a segment recording upload)
        self.takes_fn = lambda_.Function(
            self, "TakesFn",
            function_name="tuck-me-in-takes",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/takes"),
            environment=common_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # Story Content (read-only Tier 2 catalogue browsing — ThemePacks,
        # StoryTemplates, PresetCastMembers — same shape as BooksFn)
        self.story_content_fn = lambda_.Function(
            self, "StoryContentFn",
            function_name="tuck-me-in-story-content",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/story_content"),
            environment=common_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # Story Preview (internal-only visual preview of a draft
        # StoryTemplate — invoked directly via boto3/CLI, never through API
        # Gateway; there's no consumer-facing use for this. Returns a plain
        # HTML string rather than the {statusCode, body} envelope every
        # other handler uses.)
        self.story_preview_fn = lambda_.Function(
            self, "StoryPreviewFn",
            function_name="tuck-me-in-story-preview",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/story_preview"),
            environment=common_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # Story Production (internal-only Tier 2 orchestration). Manual prompt
        # composition remains available, while generation uses the configured
        # Bedrock inference profile. This is intentionally not exposed through
        # the household-facing API authorization boundary.
        # Needs Pillow for deterministic procedural effects (glow, etc.) --
        # bundled via Docker at synth/deploy time, same pattern as
        # book_ingestion above.
        prebundled_story_production = os.environ.get("STORY_PRODUCTION_PREBUNDLED_PATH")
        story_production_code = (
            lambda_.Code.from_asset(prebundled_story_production)
            if prebundled_story_production
            else lambda_.Code.from_asset(
                "functions/story_production",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            )
        )
        story_production_fn_name = "tuck-me-in-story-production"
        self.story_production_fn = lambda_.Function(
            self, "StoryProductionFn",
            function_name=story_production_fn_name,
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=story_production_code,
            environment={
                **common_env,
                "BEDROCK_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
                "STORY_PRODUCTION_JOBS_TABLE": story_production_jobs_table.table_name,
                "BEDROCK_STYLE_GUIDE_MODEL_ARN":
                    f"arn:{Aws.PARTITION}:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:inference-profile/us.stability.stable-image-style-guide-v1:0",
                "BEDROCK_REMOVE_BG_MODEL_ARN":
                    f"arn:{Aws.PARTITION}:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:inference-profile/us.stability.stable-image-remove-background-v1:0",
                # Literal, not self.story_production_fn.function_name: that
                # token renders as a Ref to this same resource, which
                # CloudFormation rejects as a circular dependency. The name
                # is already fixed above, so the plain string is equivalent.
                "STORY_PRODUCTION_SELF_FUNCTION_NAME": story_production_fn_name,
            },
            # Raised from 180s: this Lambda is only ever invoked
            # asynchronously (never synchronously through API Gateway, which
            # has its own 29s cap), so a long-running Bedrock call here never
            # blocks a caller -- it only affects billed duration if a job
            # genuinely needs the time. Stage 2 (generate_illustration_spec)
            # writes one full spec per asset for a real story and can
            # legitimately take several minutes to finish generating.
            timeout=Duration.seconds(900),
            memory_size=512,
        )
        self.story_production_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[
                f"arn:{Aws.PARTITION}:bedrock:us-east-1:{Aws.ACCOUNT_ID}:inference-profile/us.anthropic.claude-sonnet-4-6",
                f"arn:{Aws.PARTITION}:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
                # Cross-region inference profiles need both the profile ARN
                # (to use it) and the underlying foundation-model ARN with a
                # wildcard region (the profile can route to any US region) --
                # same pattern the Claude Sonnet grant above already uses.
                f"arn:{Aws.PARTITION}:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:inference-profile/us.stability.stable-image-style-guide-v1:0",
                f"arn:{Aws.PARTITION}:bedrock:*::foundation-model/stability.stable-image-style-guide-v1:0",
                f"arn:{Aws.PARTITION}:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:inference-profile/us.stability.stable-image-remove-background-v1:0",
                f"arn:{Aws.PARTITION}:bedrock:*::foundation-model/stability.stable-image-remove-background-v1:0",
            ],
        ))
        self.story_production_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["lambda:InvokeFunction"],
            # Literal ARN, not self.story_production_fn.function_arn: a GetAtt
            # back to this same function makes its own DefaultPolicy depend on
            # it, while CDK already makes the Function depend on that policy
            # (to ensure permissions exist first) -- a circular dependency
            # CloudFormation rejects. The name is fixed above, so this is
            # equivalent without the self-reference.
            resources=[f"arn:{Aws.PARTITION}:lambda:{Aws.REGION}:{Aws.ACCOUNT_ID}:function:{story_production_fn_name}"],
        ))
        # Read, not just write: _ensure_house_style_reference checks for an
        # existing cached reference before generating one.
        catalogue_assets_bucket.grant_read_write(self.story_production_fn)

        self.story_production_api_fn = lambda_.Function(
            self, "StoryProductionApiFn",
            function_name="tuck-me-in-story-production-api",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/story_production_api"),
            environment={
                "STORY_PRODUCTION_JOBS_TABLE": story_production_jobs_table.table_name,
                "STORY_PRODUCTION_FUNCTION_NAME": self.story_production_fn.function_name,
            },
            timeout=Duration.seconds(15),
            memory_size=256,
        )
        story_production_jobs_table.grant_read_write_data(self.story_production_fn)
        story_production_jobs_table.grant_read_write_data(self.story_production_api_fn)
        self.story_production_fn.grant_invoke(self.story_production_api_fn)

        # Story Instances (Mad Libs wizard: init, slot resolution/writes,
        # publish/release/unpublish)
        self.story_instances_fn = lambda_.Function(
            self, "StoryInstancesFn",
            function_name="tuck-me-in-story-instances",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/story_instances"),
            environment=common_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # Story Instance Takes (narrator begins/confirms a page recording —
        # mirrors TakesFn, addressed by page instead of EPUB cfi)
        self.story_instance_takes_fn = lambda_.Function(
            self, "StoryInstanceTakesFn",
            function_name="tuck-me-in-story-instance-takes",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/story_instance_takes"),
            environment=common_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # Alignment processor (triggered by SQS on take-confirm; the
        # version-guarded writer for word-level timing data)
        self.alignment_processor_fn = lambda_.Function(
            self, "AlignmentProcessorFn",
            function_name="tuck-me-in-alignment-processor",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("functions/alignment_processor"),
            environment=common_env,
            timeout=Duration.seconds(120),
            memory_size=512,
        )
        self.alignment_processor_fn.add_event_source(
            event_sources.SqsEventSource(
                alignment_queue,
                batch_size=1,
                report_batch_item_failures=True,
            )
        )

        # --- DynamoDB Permissions ---
        households_table.grant_read_write_data(self.households_fn)
        users_table.grant_read_write_data(self.households_fn)
        children_table.grant_read_write_data(self.households_fn)
        auto_release_grants_table.grant_read_write_data(self.households_fn)

        stories_table.grant_read_write_data(self.stories_fn)
        users_table.grant_read_data(self.stories_fn)
        households_table.grant_read_write_data(self.stories_fn)
        auto_release_grants_table.grant_read_data(self.stories_fn)
        pending_publish_notifications_table.grant_read_write_data(self.stories_fn)
        stories_table.grant_read_data(self.requests_fn)
        stories_table.grant_read_write_data(self.audio_processor_fn)

        story_requests_table.grant_read_write_data(self.requests_fn)

        linked_devices_table.grant_read_write_data(self.devices_fn)

        pending_publish_notifications_table.grant_read_write_data(self.publish_digest_fn)
        users_table.grant_read_data(self.publish_digest_fn)

        books_table.grant_read_write_data(self.book_ingestion_fn)
        book_segments_table.grant_read_write_data(self.book_ingestion_fn)
        book_imports_table.grant_read_write_data(self.book_ingestion_fn)

        books_table.grant_read_data(self.books_fn)
        book_segments_table.grant_read_data(self.books_fn)

        books_table.grant_read_data(self.takes_fn)
        book_segments_table.grant_read_data(self.takes_fn)
        users_table.grant_read_data(self.takes_fn)
        takes_table.grant_read_write_data(self.takes_fn)
        segment_recordings_table.grant_read_write_data(self.takes_fn)

        takes_table.grant_read_write_data(self.alignment_processor_fn)
        segment_recordings_table.grant_read_write_data(self.alignment_processor_fn)

        theme_packs_table.grant_read_data(self.story_content_fn)
        assets_table.grant_read_data(self.story_content_fn)
        story_templates_table.grant_read_data(self.story_content_fn)
        story_template_pages_table.grant_read_data(self.story_content_fn)
        preset_cast_members_table.grant_read_data(self.story_content_fn)
        developmental_frameworks_table.grant_read_data(self.story_content_fn)
        users_table.grant_read_data(self.story_content_fn)
        households_table.grant_read_data(self.story_content_fn)

        story_templates_table.grant_read_data(self.story_preview_fn)
        story_template_pages_table.grant_read_data(self.story_preview_fn)
        assets_table.grant_read_data(self.story_preview_fn)
        preset_cast_members_table.grant_read_data(self.story_preview_fn)

        theme_packs_table.grant_read_data(self.story_production_fn)
        assets_table.grant_read_write_data(self.story_production_fn)
        story_templates_table.grant_read_write_data(self.story_production_fn)
        story_template_pages_table.grant_read_write_data(self.story_production_fn)
        preset_cast_members_table.grant_read_data(self.story_production_fn)
        developmental_frameworks_table.grant_read_data(self.story_production_fn)

        theme_packs_table.grant_read_data(self.story_instances_fn)
        assets_table.grant_read_data(self.story_instances_fn)
        story_templates_table.grant_read_data(self.story_instances_fn)
        developmental_frameworks_table.grant_read_data(self.story_instances_fn)
        story_template_pages_table.grant_read_data(self.story_instances_fn)
        story_instances_table.grant_read_write_data(self.story_instances_fn)
        story_instance_pages_table.grant_read_write_data(self.story_instances_fn)
        story_instance_takes_table.grant_read_write_data(self.story_instances_fn)
        story_instance_segment_recordings_table.grant_read_write_data(self.story_instances_fn)
        auto_release_grants_table.grant_read_data(self.story_instances_fn)
        households_table.grant_read_write_data(self.story_instances_fn)
        users_table.grant_read_data(self.story_instances_fn)

        story_instances_table.grant_read_data(self.story_instance_takes_fn)
        story_instance_pages_table.grant_read_data(self.story_instance_takes_fn)
        story_instance_takes_table.grant_read_write_data(self.story_instance_takes_fn)
        story_instance_segment_recordings_table.grant_read_write_data(self.story_instance_takes_fn)
        users_table.grant_read_data(self.story_instance_takes_fn)

        story_instance_takes_table.grant_read_write_data(self.alignment_processor_fn)
        story_instance_segment_recordings_table.grant_read_write_data(self.alignment_processor_fn)

        # --- S3 Permissions ---
        audio_bucket.grant_read_write(self.stories_fn)
        audio_bucket.grant_read_write(self.households_fn)
        audio_bucket.grant_read_write(self.audio_processor_fn)
        audio_bucket.grant_read_write(self.takes_fn)
        audio_bucket.grant_read(self.alignment_processor_fn)
        audio_bucket.grant_read_write(self.story_instance_takes_fn)

        catalogue_source_bucket.grant_read(self.book_ingestion_fn)
        catalogue_assets_bucket.grant_write(self.book_ingestion_fn)

        # --- SQS Permissions ---
        audio_processing_queue.grant_send_messages(self.stories_fn)
        alignment_queue.grant_send_messages(self.takes_fn)
        alignment_queue.grant_send_messages(self.story_instance_takes_fn)

        # --- SNS Permissions ---
        story_request_topic.grant_publish(self.requests_fn)
        story_ready_topic.grant_publish(self.audio_processor_fn)
        recording_withdrawn_topic.grant_publish(self.stories_fn)
        publish_digest_topic.grant_publish(self.publish_digest_fn)

        # --- API Gateway ---
        self.api = apigw.RestApi(
            self, "TuckMeInApi",
            rest_api_name="Tuck Me In API",
            deploy_options=apigw.StageOptions(stage_name="v1"),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization"],
            ),
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

        # /households/join
        join_resource = households_resource.add_resource("join")
        add_auth_method(join_resource, "POST", apigw.LambdaIntegration(self.households_fn))

        # /households/{id}/invite
        invite_resource = household_by_id.add_resource("invite")
        add_auth_method(invite_resource, "POST", apigw.LambdaIntegration(self.households_fn))

        # /households/{id}/auto-release
        auto_release_resource = household_by_id.add_resource("auto-release")
        add_auth_method(auto_release_resource, "GET", apigw.LambdaIntegration(self.households_fn))
        add_auth_method(auto_release_resource, "PUT", apigw.LambdaIntegration(self.households_fn))

        # /households/{id}/children
        children_resource = household_by_id.add_resource("children")
        add_auth_method(children_resource, "POST", apigw.LambdaIntegration(self.households_fn))
        add_auth_method(children_resource, "GET", apigw.LambdaIntegration(self.households_fn))

        # /households/{id}/members
        members_resource = household_by_id.add_resource("members")
        add_auth_method(members_resource, "POST", apigw.LambdaIntegration(self.households_fn))
        add_auth_method(members_resource, "GET", apigw.LambdaIntegration(self.households_fn))
        member_by_id = members_resource.add_resource("{userId}")
        add_auth_method(member_by_id, "PUT", apigw.LambdaIntegration(self.households_fn))

        # /households/{id}/members/{userId}/photo-upload-url (presigned URL for profile photo upload)
        photo_upload_url_resource = member_by_id.add_resource("photo-upload-url")
        add_auth_method(photo_upload_url_resource, "GET", apigw.LambdaIntegration(self.households_fn))

        # /stories
        stories_resource = self.api.root.add_resource("stories")
        add_auth_method(stories_resource, "POST", apigw.LambdaIntegration(self.stories_fn))
        add_auth_method(stories_resource, "GET", apigw.LambdaIntegration(self.stories_fn))

        # /stories/limits (tier limits endpoint)
        limits_resource = stories_resource.add_resource("limits")
        add_auth_method(limits_resource, "GET", apigw.LambdaIntegration(self.stories_fn))

        story_by_id = stories_resource.add_resource("{storyId}")
        add_auth_method(story_by_id, "GET", apigw.LambdaIntegration(self.stories_fn))
        add_auth_method(story_by_id, "DELETE", apigw.LambdaIntegration(self.stories_fn))

        # /stories/{id}/upload-url (presigned URL for audio upload)
        upload_url_resource = story_by_id.add_resource("upload-url")
        add_auth_method(upload_url_resource, "GET", apigw.LambdaIntegration(self.stories_fn))

        # /stories/{id}/confirm (confirm upload complete)
        confirm_resource = story_by_id.add_resource("confirm")
        add_auth_method(confirm_resource, "POST", apigw.LambdaIntegration(self.stories_fn))

        # /stories/{id}/cover-upload-url (presigned URL for cover image upload)
        cover_upload_url_resource = story_by_id.add_resource("cover-upload-url")
        add_auth_method(cover_upload_url_resource, "GET", apigw.LambdaIntegration(self.stories_fn))

        # /stories/{id}/publish (contributor: draft -> published)
        publish_resource = story_by_id.add_resource("publish")
        add_auth_method(publish_resource, "PUT", apigw.LambdaIntegration(self.stories_fn))

        # /stories/{id}/release (admin: assign + release to child(ren))
        release_resource = story_by_id.add_resource("release")
        add_auth_method(release_resource, "PUT", apigw.LambdaIntegration(self.stories_fn))

        # /stories/{id}/unpublish (admin: withdraw from published or released)
        unpublish_resource = story_by_id.add_resource("unpublish")
        add_auth_method(unpublish_resource, "PUT", apigw.LambdaIntegration(self.stories_fn))

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

        # /books — global catalogue, read-only. Not household-scoped: every
        # authenticated user sees the same published books. No POST here —
        # ingestion is ops-only, fed by an S3 event, never through this API.
        books_resource = self.api.root.add_resource("books")
        add_auth_method(books_resource, "GET", apigw.LambdaIntegration(self.books_fn))
        book_by_id = books_resource.add_resource("{bookId}")
        add_auth_method(book_by_id, "GET", apigw.LambdaIntegration(self.books_fn))
        book_segments_resource = book_by_id.add_resource("segments")
        add_auth_method(book_segments_resource, "GET", apigw.LambdaIntegration(self.books_fn))

        # /takes — any household member may begin a take against any
        # published book's narratable segments; no per-book ownership check
        # since the catalogue itself has none.
        takes_resource = self.api.root.add_resource("takes")
        add_auth_method(takes_resource, "POST", apigw.LambdaIntegration(self.takes_fn))
        take_by_id = takes_resource.add_resource("{takeId}")
        take_confirm_resource = take_by_id.add_resource("confirm")
        add_auth_method(take_confirm_resource, "POST", apigw.LambdaIntegration(self.takes_fn))

        # /theme-packs — global catalogue, read-only, entitlement-filtered
        # by the caller's household plan.
        theme_packs_resource = self.api.root.add_resource("theme-packs")
        add_auth_method(theme_packs_resource, "GET", apigw.LambdaIntegration(self.story_content_fn))
        theme_pack_by_id = theme_packs_resource.add_resource("{themePackId}")
        add_auth_method(theme_pack_by_id, "GET", apigw.LambdaIntegration(self.story_content_fn))

        # /story-templates — global catalogue, read-only. ?themePackId= is
        # required; ?isQuickStoryDefault=true is how Tier 1 asks for the
        # fast-path template.
        story_templates_resource = self.api.root.add_resource("story-templates")
        add_auth_method(story_templates_resource, "GET", apigw.LambdaIntegration(self.story_content_fn))
        story_template_by_id = story_templates_resource.add_resource("{storyTemplateId}")
        add_auth_method(story_template_by_id, "GET", apigw.LambdaIntegration(self.story_content_fn))
        story_template_pages_resource = story_template_by_id.add_resource("pages")
        add_auth_method(story_template_pages_resource, "GET", apigw.LambdaIntegration(self.story_content_fn))

        # /preset-cast-members — global roster, read-only.
        preset_cast_members_resource = self.api.root.add_resource("preset-cast-members")
        add_auth_method(preset_cast_members_resource, "GET", apigw.LambdaIntegration(self.story_content_fn))

        # /developmental-frameworks — global reference, read-only.
        developmental_frameworks_resource = self.api.root.add_resource("developmental-frameworks")
        add_auth_method(developmental_frameworks_resource, "GET", apigw.LambdaIntegration(self.story_content_fn))

        story_production_resource = self.api.root.add_resource("story-production")
        add_auth_method(story_production_resource, "POST", apigw.LambdaIntegration(self.story_production_api_fn))
        story_production_job = story_production_resource.add_resource("{jobId}")
        add_auth_method(story_production_job, "GET", apigw.LambdaIntegration(self.story_production_api_fn))

        # /story-instances — the wizard itself
        story_instances_resource = self.api.root.add_resource("story-instances")
        add_auth_method(story_instances_resource, "POST", apigw.LambdaIntegration(self.story_instances_fn))
        add_auth_method(story_instances_resource, "GET", apigw.LambdaIntegration(self.story_instances_fn))

        story_instance_by_id = story_instances_resource.add_resource("{storyInstanceId}")
        add_auth_method(story_instance_by_id, "GET", apigw.LambdaIntegration(self.story_instances_fn))

        story_instance_current_page_resource = story_instance_by_id.add_resource("current-page")
        add_auth_method(story_instance_current_page_resource, "PUT", apigw.LambdaIntegration(self.story_instances_fn))

        story_instance_pages_resource = story_instance_by_id.add_resource("pages")
        story_instance_page_by_order = story_instance_pages_resource.add_resource("{pageOrder}")
        add_auth_method(story_instance_page_by_order, "GET", apigw.LambdaIntegration(self.story_instances_fn))

        story_instance_slot_options_resource = story_instance_page_by_order.add_resource("slot-options")
        add_auth_method(story_instance_slot_options_resource, "GET", apigw.LambdaIntegration(self.story_instances_fn))

        story_instance_slots_resource = story_instance_page_by_order.add_resource("slots")
        add_auth_method(story_instance_slots_resource, "PUT", apigw.LambdaIntegration(self.story_instances_fn))

        # /story-instances/{id}/publish (creator: draft -> published, gated
        # on completeness + all-or-nothing narration)
        story_instance_publish_resource = story_instance_by_id.add_resource("publish")
        add_auth_method(story_instance_publish_resource, "PUT", apigw.LambdaIntegration(self.story_instances_fn))

        # /story-instances/{id}/release (admin: assign + release to child(ren))
        story_instance_release_resource = story_instance_by_id.add_resource("release")
        add_auth_method(story_instance_release_resource, "PUT", apigw.LambdaIntegration(self.story_instances_fn))

        # /story-instances/{id}/unpublish (admin: withdraw from published or released)
        story_instance_unpublish_resource = story_instance_by_id.add_resource("unpublish")
        add_auth_method(story_instance_unpublish_resource, "PUT", apigw.LambdaIntegration(self.story_instances_fn))

        # /story-instance-takes — narrator begins/confirms a page recording
        story_instance_takes_resource = self.api.root.add_resource("story-instance-takes")
        add_auth_method(story_instance_takes_resource, "POST", apigw.LambdaIntegration(self.story_instance_takes_fn))
        story_instance_take_by_id = story_instance_takes_resource.add_resource("{takeId}")
        story_instance_take_confirm_resource = story_instance_take_by_id.add_resource("confirm")
        add_auth_method(story_instance_take_confirm_resource, "POST", apigw.LambdaIntegration(self.story_instance_takes_fn))
