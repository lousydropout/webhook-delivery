#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.webhook_delivery_stack import WebhookDeliveryStack

app = cdk.App()

WebhookDeliveryStack(
    app,
    "WebhookDeliveryStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1",
    ),
)

app.synth()
