from aws_cdk import Stack
from constructs import Construct

from backend.constructs.auth import AuthConstruct
from backend.constructs.database import DatabaseConstruct
from backend.constructs.storage import StorageConstruct
from backend.constructs.processing import ProcessingConstruct
from backend.constructs.api import ApiConstruct


class BackendStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Authentication (Cognito)
        auth = AuthConstruct(self, "Auth")

        # Database (DynamoDB tables)
        database = DatabaseConstruct(self, "Database")

        # Storage (S3 + CloudFront)
        storage = StorageConstruct(self, "Storage")

        # Async processing (SQS + SNS)
        processing = ProcessingConstruct(self, "Processing")

        # API Gateway + Lambda functions
        ApiConstruct(
            self, "Api",
            user_pool=auth.user_pool,
            households_table=database.households_table,
            users_table=database.users_table,
            children_table=database.children_table,
            stories_table=database.stories_table,
            story_requests_table=database.story_requests_table,
            linked_devices_table=database.linked_devices_table,
            audio_bucket=storage.audio_bucket,
            audio_processing_queue=processing.audio_processing_queue,
            story_request_topic=processing.story_request_topic,
            story_ready_topic=processing.story_ready_topic,
        )
