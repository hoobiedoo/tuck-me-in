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
            visibility_timeout=Duration.minutes(15),
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
