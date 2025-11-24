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
        # ACM Certificates for Custom Domains
        # ============================================================
        hooks_domain_name = f"hooks.{hosted_zone_url}"
        hooks_certificate = acm.Certificate(
            self,
            "TriggerApiCert",
            domain_name=hooks_domain_name,
            validation=acm.CertificateValidation.from_dns(zone),
        )

        receiver_domain_name = f"receiver.{hosted_zone_url}"
        receiver_certificate = acm.Certificate(
            self,
            "ReceiverApiCert",
            domain_name=receiver_domain_name,
            validation=acm.CertificateValidation.from_dns(zone),
        )

        # ============================================================
        # DynamoDB: TenantIdentity
        # Schema: apiKey (PK) → { tenantId, status, plan, createdAt }
        #
        # Purpose: Authentication and tenant identity only.
        # Contains NO webhook secrets or delivery configuration.
        #
        # Security Model:
        # - Lambda Authorizer reads this table to validate API keys
        # - Authorizer uses ProjectionExpression to limit fields retrieved
        # - Authorizer NEVER has access to TenantWebhookConfig (webhook secrets)
        # - API Lambda can read/write for tenant management (demo purposes)
        # ============================================================
        self.tenant_identity_table = dynamodb.Table(
            self,
            "TenantIdentity",
            table_name=f"{prefix}-TenantIdentity",
            partition_key=dynamodb.Attribute(
                name="apiKey",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            point_in_time_recovery=False,
        )

        # ============================================================
        # DynamoDB: TenantWebhookConfig
        # Schema: tenantId (PK) → { targetUrl, webhookSecret, rotationHistory, lastUpdated }
        #
        # Purpose: Webhook delivery configuration only.
        # Contains webhook secrets and target URLs for delivery.
        #
        # Security Model:
        # - Worker Lambda reads this table to get webhook secrets for HMAC signing
        # - Webhook Receiver Lambda reads this table to validate HMAC signatures
        # - Authorizer Lambda NEVER has access (enforced by IAM)
        # - API Lambda can read/write for tenant management (demo purposes)
        # ============================================================
        self.tenant_webhook_config_table = dynamodb.Table(
            self,
            "TenantWebhookConfig",
            table_name=f"{prefix}-TenantWebhookConfig",
            partition_key=dynamodb.Attribute(
                name="tenantId",
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
        #
        # createdAt Schema: Stored as STRING containing epoch seconds (e.g., "1700000000").
        # This format ensures correct lexicographical ordering for GSI queries and is
        # consistent across all code paths (create_event, update_event_status).
        # Example: str(int(time.time())) → "1700000000"
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
                type=dynamodb.AttributeType.STRING,  # Epoch seconds as string: "1700000000"
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

        # Visibility timeout must exceed Worker Lambda timeout to prevent
        # duplicate processing. Worker timeout is 60s, so visibility timeout
        # is set to 180s (3x) to account for Lambda overhead and retries.
        # If Lambda fails, message becomes visible again after 180s.
        self.events_queue = sqs.Queue(
            self,
            "EventsQueue",
            queue_name=f"{prefix}-EventsQueue",
            visibility_timeout=Duration.seconds(
                180
            ),  # Must be > Worker Lambda timeout (60s)
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=5,
                queue=self.events_dlq,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ============================================================
        # DLQ Processor Lambda (Manual Trigger)
        # Reads DLQ and requeues to main queue
        # Defined before API Lambda so API Lambda can reference it
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
                "TENANT_IDENTITY_TABLE": self.tenant_identity_table.table_name,
                "TENANT_WEBHOOK_CONFIG_TABLE": self.tenant_webhook_config_table.table_name,
                "EVENTS_TABLE": self.events_table.table_name,
                "EVENTS_QUEUE_URL": self.events_queue.queue_url,
                "EVENTS_DLQ_URL": self.events_dlq.queue_url,
                "DLQ_PROCESSOR_FUNCTION_NAME": self.dlq_processor_lambda.function_name,
            },
        )

        # API Lambda IAM Permissions (Least Privilege):
        # - Read/write TenantIdentity: Tenant creation and management
        # - Read/write TenantWebhookConfig: Webhook config updates
        # - Read/write Events: Event ingestion and retrieval
        # - Send to SQS: Enqueue events for delivery
        # - DLQ Management: Read DLQ messages, purge DLQ, invoke DLQ Processor
        # Note: API Lambda has broader access for demo/tenant management purposes.
        self.tenant_identity_table.grant_read_write_data(self.api_lambda)
        self.tenant_webhook_config_table.grant_read_write_data(self.api_lambda)
        self.events_table.grant_read_write_data(self.api_lambda)
        self.events_queue.grant_send_messages(self.api_lambda)
        # DLQ management permissions
        self.events_dlq.grant_consume_messages(self.api_lambda)
        self.events_dlq.grant_purge(self.api_lambda)
        self.dlq_processor_lambda.grant_invoke(self.api_lambda)

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
                "TENANT_IDENTITY_TABLE": self.tenant_identity_table.table_name,
            },
        )

        # Authorizer Lambda IAM Permissions (Strict Least Privilege):
        # - Read-only TenantIdentity: Validates API keys, returns tenant context
        # - NO access to TenantWebhookConfig: Never sees webhook secrets
        # - NO access to Events: Authentication only, no event data
        # - Uses ProjectionExpression in code to limit fields retrieved
        self.tenant_identity_table.grant_read_data(self.authorizer_lambda)

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
                "TENANT_WEBHOOK_CONFIG_TABLE": self.tenant_webhook_config_table.table_name,
                "EVENTS_TABLE": self.events_table.table_name,
                "EVENTS_DLQ_URL": self.events_dlq.queue_url,
            },
        )

        # Worker Lambda IAM Permissions (Least Privilege):
        # - Read/write Events: Update event delivery status
        # - Read-only TenantWebhookConfig: Get webhook secrets and target URLs
        # - Send to DLQ: Send messages to DLQ when event exceeds max attempts
        # - NO access to TenantIdentity: Does not need authentication data
        self.events_table.grant_read_write_data(self.worker_lambda)
        self.tenant_webhook_config_table.grant_read_data(self.worker_lambda)
        self.events_dlq.grant_send_messages(self.worker_lambda)

        self.worker_lambda.add_event_source(
            lambda_events.SqsEventSource(
                self.events_queue,
                batch_size=10,
                max_batching_window=Duration.seconds(0),
            )
        )

        # ============================================================
        # Webhook Receiver Lambda (Multi-tenant Webhook Validation)
        # ============================================================
        self.webhook_receiver_lambda = lambda_.Function(
            self,
            "WebhookReceiverLambda",
            function_name=f"{prefix}-WebhookReceiver",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="main.handler",
            code=lambda_.Code.from_asset(
                "../src/webhook_receiver",
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
            timeout=Duration.seconds(10),  # Webhook validation should be fast
            memory_size=256,  # Minimal memory needed for signature validation
            environment={
                "TENANT_WEBHOOK_CONFIG_TABLE": self.tenant_webhook_config_table.table_name,
            },
        )

        # Webhook Receiver Lambda IAM Permissions (Least Privilege):
        # - Read/write TenantWebhookConfig: Get webhook secrets + store global reception state
        # - NO access to TenantIdentity: Does not need authentication data
        # - NO access to Events: Validation only, does not modify events
        self.tenant_webhook_config_table.grant_read_write_data(
            self.webhook_receiver_lambda
        )

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
        # API Gateway Structure:
        # - /v1/docs, /v1/redoc, /v1/openapi.json: Public documentation (no auth)
        # - /v1/events/*: Event ingestion endpoints (requires authorizer)
        # - /v1/tenants: Tenant management (POST public, GET/PATCH require authorizer)
        #
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

        # v1 resource group
        v1_resource = self.api.root.add_resource("v1")

        # Lambda integration with proxy
        lambda_integration = apigateway.LambdaIntegration(
            self.api_lambda,
            proxy=True,
        )

        # Documentation resources (no auth required)
        docs_resource = v1_resource.add_resource("docs")
        docs_resource.add_method("GET", lambda_integration)

        redoc_resource = v1_resource.add_resource("redoc")
        redoc_resource.add_method("GET", lambda_integration)

        openapi_resource = v1_resource.add_resource("openapi.json")
        openapi_resource.add_method("GET", lambda_integration)

        # Events endpoints (all with authorizer)
        events_resource = v1_resource.add_resource("events")

        # POST /v1/events - Create event
        events_resource.add_method(
            "POST",
            lambda_integration,
            authorization_type=apigateway.AuthorizationType.CUSTOM,
            authorizer=self.token_authorizer,
        )

        # GET /v1/events - List events
        events_resource.add_method(
            "GET",
            lambda_integration,
            authorization_type=apigateway.AuthorizationType.CUSTOM,
            authorizer=self.token_authorizer,
            request_parameters={
                "method.request.querystring.status": False,
                "method.request.querystring.limit": False,
                "method.request.querystring.next_token": False,
            },
        )

        # GET /v1/events/{eventId} - Get event details
        event_id_resource = events_resource.add_resource("{eventId}")
        event_id_resource.add_method(
            "GET",
            lambda_integration,
            authorization_type=apigateway.AuthorizationType.CUSTOM,
            authorizer=self.token_authorizer,
            request_parameters={
                "method.request.path.eventId": True,
            },
        )

        # POST /v1/events/{eventId}/retry - Retry failed event
        retry_resource = event_id_resource.add_resource("retry")
        retry_resource.add_method(
            "POST",
            lambda_integration,
            authorization_type=apigateway.AuthorizationType.CUSTOM,
            authorizer=self.token_authorizer,
        )

        # Tenants endpoints
        tenants_resource = v1_resource.add_resource("tenants")

        # POST /v1/tenants - Create tenant (public, no auth required)
        tenants_resource.add_method(
            "POST",
            lambda_integration,
            authorization_type=apigateway.AuthorizationType.NONE,
        )

        # GET /v1/tenants/{tenantId} - Get tenant details
        # PATCH /v1/tenants/{tenantId} - Update tenant config
        tenant_id_resource = tenants_resource.add_resource("{tenantId}")
        tenant_id_resource.add_method(
            "GET",
            lambda_integration,
            authorization_type=apigateway.AuthorizationType.CUSTOM,
            authorizer=self.token_authorizer,
            request_parameters={
                "method.request.path.tenantId": True,
            },
        )
        tenant_id_resource.add_method(
            "PATCH",
            lambda_integration,
            authorization_type=apigateway.AuthorizationType.CUSTOM,
            authorizer=self.token_authorizer,
        )

        # Admin DLQ Management endpoints (all with authorizer)
        admin_resource = v1_resource.add_resource("admin")
        dlq_resource = admin_resource.add_resource("dlq")

        # GET /v1/admin/dlq/messages - List DLQ messages
        messages_resource = dlq_resource.add_resource("messages")
        messages_resource.add_method(
            "GET",
            lambda_integration,
            authorization_type=apigateway.AuthorizationType.CUSTOM,
            authorizer=self.token_authorizer,
            request_parameters={
                "method.request.querystring.limit": False,
            },
        )

        # POST /v1/admin/dlq/requeue - Requeue DLQ messages
        requeue_resource = dlq_resource.add_resource("requeue")
        requeue_resource.add_method(
            "POST",
            lambda_integration,
            authorization_type=apigateway.AuthorizationType.CUSTOM,
            authorizer=self.token_authorizer,
        )

        # POST /v1/admin/dlq/purge - Purge DLQ
        purge_resource = dlq_resource.add_resource("purge")
        purge_resource.add_method(
            "POST",
            lambda_integration,
            authorization_type=apigateway.AuthorizationType.CUSTOM,
            authorizer=self.token_authorizer,
        )

        # ============================================================
        # Receiver API Gateway (Separate from Main API)
        # ============================================================
        self.receiver_api = apigateway.RestApi(
            self,
            "ReceiverApi",
            rest_api_name="Webhook Receiver API",
            description="Multi-tenant webhook receiver with HMAC validation",
            deploy_options=apigateway.StageOptions(
                stage_name="prod",
                throttling_rate_limit=1000,
                throttling_burst_limit=2000,
            ),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=["*"],
                allow_methods=apigateway.Cors.ALL_METHODS,
                allow_headers=[
                    "Content-Type",
                    "Stripe-Signature",
                ],
            ),
        )

        # Tenant-specific webhook endpoint: /{tenantId}/webhook
        tenant_resource = self.receiver_api.root.add_resource("{tenantId}")
        webhook_resource = tenant_resource.add_resource("webhook")

        # POST method for webhook reception (no auth - validated via HMAC)
        webhook_resource.add_method(
            "POST",
            apigateway.LambdaIntegration(
                self.webhook_receiver_lambda,
                proxy=True,
            ),
            request_parameters={
                "method.request.path.tenantId": True,
                "method.request.header.Stripe-Signature": False,
            },
        )

        # Global control endpoints for testing retry functionality
        # POST /enable - Enable webhook reception globally (all tenants)
        enable_resource = self.receiver_api.root.add_resource("enable")
        enable_resource.add_method(
            "POST",
            apigateway.LambdaIntegration(
                self.webhook_receiver_lambda,
                proxy=True,
            ),
        )

        # POST /disable - Disable webhook reception globally (all tenants)
        disable_resource = self.receiver_api.root.add_resource("disable")
        disable_resource.add_method(
            "POST",
            apigateway.LambdaIntegration(
                self.webhook_receiver_lambda,
                proxy=True,
            ),
        )

        # GET /status - Get global webhook reception status
        status_resource = self.receiver_api.root.add_resource("status")
        status_resource.add_method(
            "GET",
            apigateway.LambdaIntegration(
                self.webhook_receiver_lambda,
                proxy=True,
            ),
        )

        # Health check endpoint: /health
        health_resource = self.receiver_api.root.add_resource("health")
        health_resource.add_method(
            "GET",
            apigateway.LambdaIntegration(
                self.webhook_receiver_lambda,
                proxy=True,
            ),
        )

        # Documentation endpoints: /docs
        docs_resource = self.receiver_api.root.add_resource("docs")
        docs_resource.add_method(
            "GET",
            apigateway.LambdaIntegration(
                self.webhook_receiver_lambda,
                proxy=True,
            ),
        )

        # OpenAPI schema endpoint: /openapi.json
        openapi_resource = self.receiver_api.root.add_resource("openapi.json")
        openapi_resource.add_method(
            "GET",
            apigateway.LambdaIntegration(
                self.webhook_receiver_lambda,
                proxy=True,
            ),
        )

        # ReDoc endpoint: /redoc
        redoc_resource = self.receiver_api.root.add_resource("redoc")
        redoc_resource.add_method(
            "GET",
            apigateway.LambdaIntegration(
                self.webhook_receiver_lambda,
                proxy=True,
            ),
        )

        # Custom domain mapping for hooks API (REGIONAL endpoint, no base path)
        # REGIONAL endpoint type provides better latency and lower cost than EDGE.
        # Empty base_path ("") maps domain directly to API root, so URLs are:
        # https://hooks.vincentchan.cloud/v1/events (not /prod/v1/events)
        hooks_custom_domain = apigateway.DomainName(
            self,
            "TriggerApiCustomDomain",
            domain_name=hooks_domain_name,
            certificate=hooks_certificate,
            endpoint_type=apigateway.EndpointType.REGIONAL,
        )

        # Map to root path (empty base path - no stripping needed)
        # This allows clean URLs without stage prefix in the path
        hooks_custom_domain.add_base_path_mapping(
            self.api,
            base_path="",  # Empty = root path, no base path stripping
            stage=self.api.deployment_stage,
        )

        # DNS A record for hooks API
        route53.ARecord(
            self,
            "TriggerApiAliasRecord",
            zone=zone,
            record_name="hooks",
            target=route53.RecordTarget.from_alias(
                targets.ApiGatewayDomain(hooks_custom_domain)
            ),
        )

        # Custom domain mapping for receiver API (REGIONAL endpoint, no base path)
        # Same pattern as hooks API: REGIONAL endpoint with root path mapping
        # URLs: https://receiver.vincentchan.cloud/{tenantId}/webhook
        receiver_custom_domain = apigateway.DomainName(
            self,
            "ReceiverApiCustomDomain",
            domain_name=receiver_domain_name,
            certificate=receiver_certificate,
            endpoint_type=apigateway.EndpointType.REGIONAL,
        )

        # Map to root path (empty base path - no stripping needed)
        receiver_custom_domain.add_base_path_mapping(
            self.receiver_api,
            base_path="",  # Empty = root path, no base path stripping
            stage=self.receiver_api.deployment_stage,
        )

        # DNS A record for receiver API
        route53.ARecord(
            self,
            "ReceiverApiAliasRecord",
            zone=zone,
            record_name="receiver",
            target=route53.RecordTarget.from_alias(
                targets.ApiGatewayDomain(receiver_custom_domain)
            ),
        )

        # ============================================================
        # Outputs
        # ============================================================
        CfnOutput(
            self,
            "TenantIdentityTableName",
            value=self.tenant_identity_table.table_name,
        )

        CfnOutput(
            self,
            "TenantWebhookConfigTableName",
            value=self.tenant_webhook_config_table.table_name,
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
            value=f"https://{hooks_custom_domain.domain_name}",
        )

        # Webhook Receiver Outputs
        CfnOutput(
            self,
            "WebhookReceiverFunctionName",
            value=self.webhook_receiver_lambda.function_name,
            description="Webhook receiver Lambda function name",
        )

        CfnOutput(
            self,
            "WebhookReceiverDomainUrl",
            value=f"https://{receiver_custom_domain.domain_name}",
            description="Webhook receiver custom domain URL",
        )

        CfnOutput(
            self,
            "WebhookReceiverEndpoint",
            value=f"https://receiver.{hosted_zone_url}/{{tenantId}}/webhook",
            description="Webhook receiver endpoint URL template",
        )

        CfnOutput(
            self,
            "WebhookReceiverHealthEndpoint",
            value=f"https://receiver.{hosted_zone_url}/health",
            description="Webhook receiver health check endpoint",
        )
