#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.trigger_api_stack import TriggerApiStack

app = cdk.App()

TriggerApiStack(
    app,
    "TriggerApiStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1"
    )
)

app.synth()
