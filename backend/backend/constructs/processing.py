from aws_cdk import (
    Duration,
    aws_sqs as sqs,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subs,
)
from constructs import Construct


class ProcessingConstruct(Construct):

    def __init__(self, scope: Construct, id: str) -> None:
        super().__init__(scope, id)

        # Dead letter queue for failed audio processing jobs
        self.audio_dlq = sqs.Queue(
            self, "AudioProcessingDLQ",
            queue_name="tuck-me-in-audio-processing-dlq",
            retention_period=Duration.days(14),
        )

        # SQS queue for async audio processing
        self.audio_processing_queue = sqs.Queue(
            self, "AudioProcessingQueue",
            queue_name="tuck-me-in-audio-processing",
            visibility_timeout=Duration.seconds(60),
            retention_period=Duration.days(7),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.audio_dlq,
            ),
        )

        # SNS topic for story request notifications
        self.story_request_topic = sns.Topic(
            self, "StoryRequestTopic",
            topic_name="tuck-me-in-story-requests",
            display_name="Tuck Me In Story Requests",
        )

        # SNS topic for story ready notifications
        self.story_ready_topic = sns.Topic(
            self, "StoryReadyTopic",
            topic_name="tuck-me-in-story-ready",
            display_name="Tuck Me In Story Ready",
        )

        # SNS topic for the batched "new recordings published" digest to parents
        self.publish_digest_topic = sns.Topic(
            self, "PublishDigestTopic",
            topic_name="tuck-me-in-publish-digest",
            display_name="Tuck Me In Publish Digest",
        )

        # SNS topic for "your recording was unpublished" notifications to contributors
        self.recording_withdrawn_topic = sns.Topic(
            self, "RecordingWithdrawnTopic",
            topic_name="tuck-me-in-recording-withdrawn",
            display_name="Tuck Me In Recording Withdrawn",
        )

        # Dead letter queue for failed book ingestion jobs
        self.book_ingestion_dlq = sqs.Queue(
            self, "BookIngestionDLQ",
            queue_name="tuck-me-in-book-ingestion-dlq",
            retention_period=Duration.days(14),
        )

        # SQS queue for async epub ingestion — fed directly by an S3 event
        # notification on CatalogueSourceBucket, not by any application
        # code. Ingestion parses a whole book per message, which can take
        # longer than audio processing's default visibility window.
        self.book_ingestion_queue = sqs.Queue(
            self, "BookIngestionQueue",
            queue_name="tuck-me-in-book-ingestion",
            visibility_timeout=Duration.seconds(180),
            retention_period=Duration.days(7),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.book_ingestion_dlq,
            ),
        )

        # Dead letter queue for failed alignment jobs
        self.alignment_dlq = sqs.Queue(
            self, "AlignmentDLQ",
            queue_name="tuck-me-in-alignment-dlq",
            retention_period=Duration.days(14),
        )

        # SQS queue for forced alignment — fed by the takes Lambda on a
        # successful upload confirm, one job per take.
        self.alignment_queue = sqs.Queue(
            self, "AlignmentQueue",
            queue_name="tuck-me-in-alignment",
            visibility_timeout=Duration.seconds(120),
            retention_period=Duration.days(7),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.alignment_dlq,
            ),
        )
