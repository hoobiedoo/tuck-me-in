from pathlib import Path

from aws_cdk import (
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3_deployment as s3_deployment,
)
from constructs import Construct


class StorageConstruct(Construct):

    def __init__(self, scope: Construct, id: str) -> None:
        super().__init__(scope, id)

        # S3 bucket for audio storage
        self.audio_bucket = s3.Bucket(
            self, "AudioBucket",
            bucket_name=None,  # auto-generated unique name
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="TransitionToIA",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(90),
                        )
                    ],
                ),
            ],
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.POST],
                    allowed_origins=["*"],  # tighten in production
                    allowed_headers=["*"],
                    max_age=3600,
                )
            ],
        )

        # S3 bucket for uploaded epub source files. Ops-only: no household
        # code, no presigned upload URLs, no CDN — books are ingested by
        # dropping a file here directly (S3 event triggers ingestion), not
        # through the app.
        self.catalogue_source_bucket = s3.Bucket(
            self, "CatalogueSourceBucket",
            bucket_name=None,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # S3 bucket for extracted book cover/illustration assets. Shared,
        # non-sensitive catalogue content (unlike household audio) — served
        # through CloudFront but without signed URLs, since every household
        # sees the same published books.
        self.catalogue_assets_bucket = s3.Bucket(
            self, "CatalogueAssetsBucket",
            bucket_name=None,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Private origin for the Expo web build. The site is public only
        # through CloudFront; the bucket itself never allows public access.
        self.web_app_bucket = s3.Bucket(
            self, "WebAppBucket",
            bucket_name=None,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.web_app_distribution = cloudfront.Distribution(
            self, "WebAppCDN",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.web_app_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                compress=True,
            ),
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
        )

        web_build_path = Path(__file__).resolve().parents[3] / "app" / "dist"
        if not web_build_path.is_dir():
            raise ValueError(
                f"Web build not found at {web_build_path}. "
                "Run `cd app && npx expo export --platform web` before CDK synth or deploy."
            )

        s3_deployment.BucketDeployment(
            self, "DeployWebApp",
            sources=[s3_deployment.Source.asset(str(web_build_path))],
            destination_bucket=self.web_app_bucket,
            distribution=self.web_app_distribution,
            distribution_paths=["/*"],
            prune=True,
        )

        # CloudFront distribution for secure audio + catalogue asset delivery
        self.distribution = cloudfront.Distribution(
            self, "AudioCDN",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.audio_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            additional_behaviors={
                "book-assets/*": cloudfront.BehaviorOptions(
                    origin=origins.S3BucketOrigin.with_origin_access_control(self.catalogue_assets_bucket),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                    cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                ),
            },
        )

        CfnOutput(self, "AudioBucketName", value=self.audio_bucket.bucket_name)
        CfnOutput(self, "CatalogueSourceBucketName", value=self.catalogue_source_bucket.bucket_name)
        CfnOutput(self, "CatalogueAssetsBucketName", value=self.catalogue_assets_bucket.bucket_name)
        CfnOutput(self, "DistributionDomainName", value=self.distribution.distribution_domain_name)
        CfnOutput(self, "WebAppBucketName", value=self.web_app_bucket.bucket_name)
        CfnOutput(
            self, "WebAppUrl",
            value=f"https://{self.web_app_distribution.distribution_domain_name}",
        )
