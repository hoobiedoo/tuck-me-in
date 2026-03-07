from aws_cdk import (
    RemovalPolicy,
    aws_dynamodb as dynamodb,
)
from constructs import Construct


class DatabaseConstruct(Construct):

    def __init__(self, scope: Construct, id: str) -> None:
        super().__init__(scope, id)

        # Households table
        self.households_table = dynamodb.Table(
            self, "HouseholdsTable",
            table_name="tuck-me-in-households",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Users table
        self.users_table = dynamodb.Table(
            self, "UsersTable",
            table_name="tuck-me-in-users",
            partition_key=dynamodb.Attribute(
                name="userId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.users_table.add_global_secondary_index(
            index_name="byHousehold",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Children table
        self.children_table = dynamodb.Table(
            self, "ChildrenTable",
            table_name="tuck-me-in-children",
            partition_key=dynamodb.Attribute(
                name="childId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.children_table.add_global_secondary_index(
            index_name="byHousehold",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Stories table
        self.stories_table = dynamodb.Table(
            self, "StoriesTable",
            table_name="tuck-me-in-stories",
            partition_key=dynamodb.Attribute(
                name="storyId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.stories_table.add_global_secondary_index(
            index_name="byHousehold",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
        )
        self.stories_table.add_global_secondary_index(
            index_name="byReader",
            partition_key=dynamodb.Attribute(
                name="readerId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Story Requests table
        self.story_requests_table = dynamodb.Table(
            self, "StoryRequestsTable",
            table_name="tuck-me-in-story-requests",
            partition_key=dynamodb.Attribute(
                name="requestId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.story_requests_table.add_global_secondary_index(
            index_name="byHousehold",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
        )
        self.story_requests_table.add_global_secondary_index(
            index_name="byRequestedReader",
            partition_key=dynamodb.Attribute(
                name="requestedReaderId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Linked Devices table
        self.linked_devices_table = dynamodb.Table(
            self, "LinkedDevicesTable",
            table_name="tuck-me-in-linked-devices",
            partition_key=dynamodb.Attribute(
                name="deviceId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.linked_devices_table.add_global_secondary_index(
            index_name="byHousehold",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
        )
