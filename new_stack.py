from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    BundlingOptions,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_apigateway as apigateway,
    aws_sqs as sqs,
)
from aws_cdk import aws_apigateway as apigateway
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets


from aws_cdk import aws_lambda_event_sources as lambda_events
from constructs import Construct

prefix = "Vincent-TriggerApi"


class TriggerApiStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Hosted zone
        zone = route53.HostedZone.from_hosted_zone_attributes(
            self,
            "VincentHostedZone",
            hosted_zone_id="Z00669322LNYAWLYNIHGN",
            zone_name="vincentchan.cloud",
        )

        # Certificate
        certificate = acm.Certificate(
            self,
            "TriggerApiCert",
            domain_name="hooks.vincentchan.cloud",
            validation=acm.CertificateValidation.from_dns(zone),
        )

        # Custom domain mapping
        custom_domain = apigateway.DomainName(
            self,
            "TriggerApiCustomDomain",
            domain_name="hooks.vincentchan.cloud",
            certificate=certificate,
            endpoint_type=apigateway.EndpointType.EDGE,  # or REGIONAL
        )

        # Map custom domain to the API stage
        custom_domain.add_base_path_mapping(
            self.api,
            base_path="",
            stage=self.api.deployment_stage,
        )

        # DNS record
        route53.ARecord(
            self,
            "TriggerApiAliasRecord",
            zone=zone,
            record_name="triggers",
            target=route53.RecordTarget.from_alias(
                targets.ApiGatewayDomain(custom_domain)
            ),
        )

        # ============================================================
        # DynamoDB: TenantApiKeys
        # Stores per-tenant API keys and routing config
        # PK: apiKey (string)
        #    item: {
        #      apiKey: "...",              # header token
        #      tenantId: "tenant-123",
        #      targetUrl: "https://...",   # where to POST
        #      isActive: true,
        #      createdAt: "ISO8601"
        #    }
        # ============================================================
        self.tenant_api_keys_table = dynamodb.Table(
            self,
            "TenantApiKeys",
            table_name=f"{prefix}-TenantApiKeys",
            partition_key=dynamodb.Attribute(
                name="apiKey",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,  # dev/demo only
            point_in_time_recovery=False,
        )

        # ============================================================
        # DynamoDB: Events
        # PK: tenantId, SK: eventId
        # GSI: status-index for querying by delivery status
        #
        # item example:
        # {
        #   tenantId: "tenant-123",
        #   eventId: "evt_...",
        #   status: "PENDING" | "DELIVERED" | "FAILED",
        #   createdAt: "ISO8601",
        #   lastAttemptAt: "ISO8601",
        #   attempts: 0,
        #   payload: {...},    # original event body
        #   targetUrl: "https://...",
        #   ttl: 1735689600    # optional expiry
        # }
        # ============================================================
        self.events_table = dynamodb.Table(
            self,
            "Events",
            table_name=f"{prefix}-Events",
            partition_key=dynamodb.Attribute(
                name="tenantId",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="eventId",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,  # dev/demo only
            point_in_time_recovery=False,
            time_to_live_attribute="ttl",
        )

        self.events_table.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(
                name="status",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="createdAt",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ============================================================
        # SQS: Event Delivery Queue + DLQ
        # API Lambda -> SQS -> Worker Lambda
        # ============================================================
        self.events_dlq = sqs.Queue(
            self,
            "EventsDlq",
            queue_name=f"{prefix}-EventsDlq",
            retention_period=Duration.days(14),
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.events_queue = sqs.Queue(
            self,
            "EventsQueue",
            queue_name=f"{prefix}-EventsQueue",
            visibility_timeout=Duration.seconds(60),
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=5,
                queue=self.events_dlq,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ============================================================
        # Lambda Layer: shared Python dependencies
        # Contains libraries only (NO app code)
        # ============================================================
        self.dependencies_layer = lambda_.LayerVersion(
            self,
            "CommonDependenciesLayer",
            code=lambda_.Code.from_asset(
                "../",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output/python",
                    ],
                ),
            ),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Shared Python deps: FastAPI, Mangum, HTTP client, etc.",
        )

        # ============================================================
        # API Lambda (FastAPI + Mangum)
        # Responsibilities:
        #  - Validate X-Api-Key / Authorization header against TenantApiKeys
        #  - Persist event into Events table (status=PENDING)
        #  - Enqueue SQS job with tenantId + eventId
        # ============================================================
        self.api_lambda = lambda_.Function(
            self,
            "ApiLambda",
            function_name=f"{prefix}-ApiHandler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="main.handler",  # src/api/main.py -> handler
            code=lambda_.Code.from_asset("../src/api"),
            layers=[self.dependencies_layer],
            timeout=Duration.seconds(30),
            memory_size=1024,
            environment={
                "TENANT_API_KEYS_TABLE": self.tenant_api_keys_table.table_name,
                "EVENTS_TABLE": self.events_table.table_name,
                "EVENTS_QUEUE_URL": self.events_queue.queue_url,
            },
        )

        self.tenant_api_keys_table.grant_read_data(self.api_lambda)
        self.events_table.grant_read_write_data(self.api_lambda)
        self.events_queue.grant_send_messages(self.api_lambda)

        # ============================================================
        # Worker Lambda
        # Responsibilities:
        #  - Triggered by SQS (EventsQueue)
        #  - For each message:
        #       * load event record from Events table
        #       * load tenant routing config from TenantApiKeys
        #       * POST to targetUrl
        #       * update status: DELIVERED or FAILED (+attempts, lastAttemptAt)
        #  - Let SQS redrive to DLQ after max_receive_count
        # ============================================================
        self.worker_lambda = lambda_.Function(
            self,
            "WorkerLambda",
            function_name=f"{prefix}-WorkerHandler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.main",  # src/worker/handler.py -> main(event, context)
            code=lambda_.Code.from_asset("../src/worker"),
            layers=[self.dependencies_layer],
            timeout=Duration.seconds(60),
            memory_size=1024,
            environment={
                "TENANT_API_KEYS_TABLE": self.tenant_api_keys_table.table_name,
                "EVENTS_TABLE": self.events_table.table_name,
            },
        )

        self.events_table.grant_read_write_data(self.worker_lambda)
        self.tenant_api_keys_table.grant_read_data(self.worker_lambda)

        self.worker_lambda.add_event_source(
            lambda_events.SqsEventSource(
                self.events_queue,
                batch_size=10,
                max_batching_window=Duration.seconds(5),
            )
        )

        # ============================================================
        # API Gateway: Lambda proxy -> FastAPI app
        # Ingestion endpoint:
        #   POST /events
        #   Headers: X-Api-Key: <tenant api key>
        # ============================================================
        self.api = apigateway.LambdaRestApi(
            self,
            "TriggerApi",
            handler=self.api_lambda,
            proxy=True,  # all routing handled by FastAPI
            rest_api_name="Trigger Ingestion API",
            description="Multi-tenant event ingestion API with SQS-backed delivery.",
            deploy_options=apigateway.StageOptions(
                stage_name="prod",
                throttling_rate_limit=500,
                throttling_burst_limit=1000,
            ),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=["*"],  # you can lock this down later
                allow_methods=apigateway.Cors.ALL_METHODS,
                allow_headers=[
                    "Content-Type",
                    "Authorization",
                    "X-Amz-Date",
                    "X-Api-Key",
                    "X-Amz-Security-Token",
                ],
            ),
        )

        # ============================================================
        # Outputs
        # ============================================================
        CfnOutput(
            self,
            "TenantApiKeysTableName",
            value=self.tenant_api_keys_table.table_name,
            description="TenantApiKeys table name",
        )

        CfnOutput(
            self,
            "EventsTableName",
            value=self.events_table.table_name,
            description="Events table name",
        )

        CfnOutput(
            self,
            "EventsQueueUrl",
            value=self.events_queue.queue_url,
            description="Events SQS queue URL",
        )

        CfnOutput(
            self,
            "ApiLambdaArn",
            value=self.api_lambda.function_arn,
            description="API Lambda function ARN",
        )

        CfnOutput(
            self,
            "WorkerLambdaArn",
            value=self.worker_lambda.function_arn,
            description="Worker Lambda function ARN",
        )

        CfnOutput(
            self,
            "ApiUrl",
            value=self.api.url,
            description="API Gateway endpoint URL",
        )
