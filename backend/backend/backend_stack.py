from aws_cdk import Stack, aws_s3 as s3, aws_s3_notifications as s3_notifications
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

        # Book ingestion is triggered by dropping a file in the catalogue
        # source bucket, not by any application code — wire that directly
        # here, since it's the one place both constructs are in scope.
        storage.catalogue_source_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3_notifications.SqsDestination(processing.book_ingestion_queue),
            s3.NotificationKeyFilter(suffix=".epub"),
        )

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
            auto_release_grants_table=database.auto_release_grants_table,
            pending_publish_notifications_table=database.pending_publish_notifications_table,
            books_table=database.books_table,
            book_segments_table=database.book_segments_table,
            book_imports_table=database.book_imports_table,
            takes_table=database.takes_table,
            segment_recordings_table=database.segment_recordings_table,
            theme_packs_table=database.theme_packs_table,
            assets_table=database.assets_table,
            story_templates_table=database.story_templates_table,
            story_template_pages_table=database.story_template_pages_table,
            preset_cast_members_table=database.preset_cast_members_table,
            developmental_frameworks_table=database.developmental_frameworks_table,
            story_production_jobs_table=database.story_production_jobs_table,
            story_instances_table=database.story_instances_table,
            story_instance_pages_table=database.story_instance_pages_table,
            story_instance_takes_table=database.story_instance_takes_table,
            story_instance_segment_recordings_table=database.story_instance_segment_recordings_table,
            audio_bucket=storage.audio_bucket,
            cdn_domain=storage.distribution.distribution_domain_name,
            catalogue_source_bucket=storage.catalogue_source_bucket,
            catalogue_assets_bucket=storage.catalogue_assets_bucket,
            audio_processing_queue=processing.audio_processing_queue,
            book_ingestion_queue=processing.book_ingestion_queue,
            alignment_queue=processing.alignment_queue,
            story_request_topic=processing.story_request_topic,
            story_ready_topic=processing.story_ready_topic,
            publish_digest_topic=processing.publish_digest_topic,
            recording_withdrawn_topic=processing.recording_withdrawn_topic,
        )
