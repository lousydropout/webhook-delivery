from aws_cdk import (
    Stack,
    aws_dynamodb as dynamodb,
    RemovalPolicy,
    CfnOutput
)
from constructs import Construct


class TriggerApiStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # DynamoDB Table: TenantApiKeys
        self.api_keys_table = dynamodb.Table(
            self,
            "TenantApiKeys",
            table_name="TriggerApi-TenantApiKeys",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,  # For dev/demo only
            point_in_time_recovery=False
        )

        # DynamoDB Table: Events
        self.events_table = dynamodb.Table(
            self,
            "Events",
            table_name="TriggerApi-Events",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,  # For dev/demo only
            point_in_time_recovery=False
        )

        # GSI: status-index for querying undelivered events
        self.events_table.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(
                name="gsi1pk",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="gsi1sk",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL
        )

        # Outputs
        CfnOutput(
            self,
            "ApiKeysTableName",
            value=self.api_keys_table.table_name,
            description="TenantApiKeys table name"
        )

        CfnOutput(
            self,
            "EventsTableName",
            value=self.events_table.table_name,
            description="Events table name"
        )
