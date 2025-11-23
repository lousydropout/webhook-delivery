import os
from dotenv import load_dotenv
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
    aws_certificatemanager as acm,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_lambda_event_sources as lambda_events,
)
from constructs import Construct

# Load environment variables from .env file
load_dotenv()


prefix = os.getenv("PREFIX")
if not prefix:
    raise ValueError("PREFIX must be set in .env file")



class WebhookDeliveryStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================================
        # Route53 Hosted Zone (existing)
        # ============================================================
        hosted_zone_id = os.getenv("HOSTED_ZONE_ID")
        hosted_zone_url = os.getenv("HOSTED_ZONE_URL")

        if not hosted_zone_id or not hosted_zone_url:
            raise ValueError(
                "HOSTED_ZONE_ID and HOSTED_ZONE_URL must be set in .env file"
            )

        zone = route53.HostedZone.from_hosted_zone_attributes(
            self,
            "HostedZone",
            hosted_zone_id=hosted_zone_id,
            zone_name=hosted_zone_url,
        )

        # ============================================================
        # ACM Certificate for Custom Domain
        # ============================================================
        domain_name = f"hooks.{hosted_zone_url}"
        certificate = acm.Certificate(
            self,
            "TriggerApiCert",
            domain_name=domain_name,
            validation=acm.CertificateValidation.from_dns(zone),
        )

        # ============================================================
        # DynamoDB: TenantApiKeys
        # Schema: apiKey (PK) → { tenantId, targetUrl, webhookSecret, isActive }
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
            removal_policy=RemovalPolicy.DESTROY,
            point_in_time_recovery=False,
        )

        # ============================================================
        # DynamoDB: Events
        # Schema: tenantId (PK), eventId (SK)
        # GSI: status-index (status PK, createdAt SK)
        # Attributes: status, payload, targetUrl, attempts, lastAttemptAt, ttl
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
            removal_policy=RemovalPolicy.DESTROY,
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
        # API Lambda (Event Ingestion)
        # Bundled dependencies, no layer
        # ============================================================
        self.api_lambda = lambda_.Function(
            self,
            "ApiLambda",
            function_name=f"{prefix}-ApiHandler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="main.handler",
            code=lambda_.Code.from_asset(
                "../src/api",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && "
                        + "cp -r . /asset-output",
                    ],
                ),
            ),
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
        # Authorizer Lambda
        # Validates Bearer tokens and returns tenant context
        # ============================================================
        self.authorizer_lambda = lambda_.Function(
            self,
            "AuthorizerLambda",
            function_name=f"{prefix}-Authorizer",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(
                "../src/authorizer",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && "
                        + "cp -r . /asset-output",
                    ],
                ),
            ),
            timeout=Duration.seconds(10),
            memory_size=256,
            environment={
                "TENANT_API_KEYS_TABLE": self.tenant_api_keys_table.table_name,
            },
        )

        self.tenant_api_keys_table.grant_read_data(self.authorizer_lambda)

        # ============================================================
        # Worker Lambda (Webhook Delivery)
        # SQS triggered, bundled dependencies
        # ============================================================
        self.worker_lambda = lambda_.Function(
            self,
            "WorkerLambda",
            function_name=f"{prefix}-WorkerHandler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.main",
            code=lambda_.Code.from_asset(
                "../src/worker",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && "
                        + "cp -r . /asset-output",
                    ],
                ),
            ),
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
        # DLQ Processor Lambda (Manual Trigger)
        # Reads DLQ and requeues to main queue
        # ============================================================
        self.dlq_processor_lambda = lambda_.Function(
            self,
            "DlqProcessorLambda",
            function_name=f"{prefix}-DlqProcessor",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.main",
            code=lambda_.Code.from_asset(
                "../src/dlq_processor",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && "
                        + "cp -r . /asset-output",
                    ],
                ),
            ),
            timeout=Duration.seconds(300),
            memory_size=512,
            environment={
                "EVENTS_DLQ_URL": self.events_dlq.queue_url,
                "EVENTS_QUEUE_URL": self.events_queue.queue_url,
            },
        )

        self.events_dlq.grant_consume_messages(self.dlq_processor_lambda)
        self.events_queue.grant_send_messages(self.dlq_processor_lambda)

        # ============================================================
        # API Gateway Token Authorizer
        # ============================================================
        self.token_authorizer = apigateway.TokenAuthorizer(
            self,
            "ApiTokenAuthorizer",
            handler=self.authorizer_lambda,
            identity_source="method.request.header.Authorization",
            results_cache_ttl=Duration.minutes(5),
        )

        # ============================================================
        # API Gateway with Custom Domain
        # ============================================================
        # Create RestApi manually to support explicit /v1/{proxy+} resource
        self.api = apigateway.RestApi(
            self,
            "TriggerApi",
            rest_api_name="Webhook Delivery API",
            description="Multi-tenant webhook delivery with SQS-backed processing",
            deploy_options=apigateway.StageOptions(
                stage_name="prod",
                throttling_rate_limit=500,
                throttling_burst_limit=1000,
            ),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=["*"],
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

        # Create /v1 resource
        v1_resource = self.api.root.add_resource("v1")

        # Lambda integration with proxy
        lambda_integration = apigateway.LambdaIntegration(
            self.api_lambda,
            proxy=True,
        )

        # Add public docs endpoints (no auth required)
        docs_resource = v1_resource.add_resource("docs")
        docs_resource.add_method("GET", lambda_integration)

        redoc_resource = v1_resource.add_resource("redoc")
        redoc_resource.add_method("GET", lambda_integration)

        openapi_resource = v1_resource.add_resource("openapi.json")
        openapi_resource.add_method("GET", lambda_integration)

        # Create /v1/events resource with authorizer
        events_resource = v1_resource.add_resource("events")
        events_resource.add_method(
            "POST",
            lambda_integration,
            authorization_type=apigateway.AuthorizationType.CUSTOM,
            authorizer=self.token_authorizer,
        )

        # Custom domain mapping (REGIONAL endpoint, no base path)
        custom_domain = apigateway.DomainName(
            self,
            "TriggerApiCustomDomain",
            domain_name=domain_name,
            certificate=certificate,
            endpoint_type=apigateway.EndpointType.REGIONAL,
        )

        # Map to root path (empty base path - no stripping needed)
        custom_domain.add_base_path_mapping(
            self.api,
            base_path="",  # Empty = root path, no base path stripping
            stage=self.api.deployment_stage,
        )

        # DNS A record
        route53.ARecord(
            self,
            "TriggerApiAliasRecord",
            zone=zone,
            record_name="hooks",
            target=route53.RecordTarget.from_alias(
                targets.ApiGatewayDomain(custom_domain)
            ),
        )

        # ============================================================
        # Outputs
        # ============================================================
        CfnOutput(
            self,
            "TenantApiKeysTableName",
            value=self.tenant_api_keys_table.table_name,
        )

        CfnOutput(
            self,
            "EventsTableName",
            value=self.events_table.table_name,
        )

        CfnOutput(
            self,
            "EventsQueueUrl",
            value=self.events_queue.queue_url,
        )

        CfnOutput(
            self,
            "EventsDlqUrl",
            value=self.events_dlq.queue_url,
        )

        CfnOutput(
            self,
            "CustomDomainUrl",
            value=f"https://{custom_domain.domain_name}",
        )
