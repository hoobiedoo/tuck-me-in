#!/usr/bin/env python3
import os

import aws_cdk as cdk

from backend.backend_stack import BackendStack

app = cdk.App()
BackendStack(
    app, "TuckMeInBackend",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION", "us-east-1"),
    ),
)

app.synth()
