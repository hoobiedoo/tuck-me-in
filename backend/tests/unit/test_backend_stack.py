import aws_cdk as core
import aws_cdk.assertions as assertions

from backend.backend_stack import BackendStack

def test_web_app_hosting_created():
    app = core.App()
    stack = BackendStack(app, "backend")
    template = assertions.Template.from_stack(stack)

    template.resource_count_is("AWS::CloudFront::Distribution", 2)
    template.has_resource_properties("AWS::CloudFront::Distribution", {
        "DistributionConfig": {
            "DefaultRootObject": "index.html",
            "Enabled": True,
        },
    })
    template.has_resource_properties("AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        },
    })
