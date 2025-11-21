from aws_cdk import (
    Stack,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_apigateway as apigateway,
    Duration,
    RemovalPolicy,
    CfnOutput,
    BundlingOptions
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

        # Lambda Layer for Python dependencies
        self.dependencies_layer = lambda_.LayerVersion(
            self,
            "DependenciesLayer",
            code=lambda_.Code.from_asset(
                "../",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output/python && " +
                        "cp -r /asset-input/src /asset-output/python/"
                    ]
                )
            ),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_11],
            description="FastAPI, Mangum, Boto3, Pydantic"
        )

        # Lambda Function for API (FastAPI application)
        self.api_lambda = lambda_.Function(
            self,
            "ApiLambda",
            function_name="TriggerApi-ApiHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="main.handler",
            code=lambda_.Code.from_asset("../src/lambda_handlers/api"),
            layers=[self.dependencies_layer],
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={
                "API_KEYS_TABLE": self.api_keys_table.table_name,
                "EVENTS_TABLE": self.events_table.table_name
            }
        )

        # Grant DynamoDB permissions
        self.api_keys_table.grant_read_data(self.api_lambda)
        self.events_table.grant_read_write_data(self.api_lambda)

        # API Gateway REST API
        self.api = apigateway.LambdaRestApi(
            self,
            "TriggerApi",
            handler=self.api_lambda,
            proxy=True,  # Forward all requests to Lambda
            rest_api_name="Trigger Ingestion API",
            description="Multi-tenant event ingestion API",
            deploy_options=apigateway.StageOptions(
                stage_name="prod",
                throttling_rate_limit=1000,
                throttling_burst_limit=2000
            ),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=apigateway.Cors.ALL_ORIGINS,
                allow_methods=apigateway.Cors.ALL_METHODS,
                allow_headers=[
                    "Content-Type",
                    "Authorization",
                    "X-Amz-Date",
                    "X-Api-Key",
                    "X-Amz-Security-Token"
                ]
            )
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

        CfnOutput(
            self,
            "ApiLambdaArn",
            value=self.api_lambda.function_arn,
            description="API Lambda function ARN"
        )

        CfnOutput(
            self,
            "ApiUrl",
            value=self.api.url,
            description="API Gateway endpoint URL"
        )
