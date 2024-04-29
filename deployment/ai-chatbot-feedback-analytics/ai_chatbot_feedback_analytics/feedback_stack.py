from time import strftime
from constructs import Construct
from aws_cdk import Stack, Duration, CfnOutput, Tags, Aws
from aws_cdk import (
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_s3 as s3,
    RemovalPolicy,
    aws_cloudtrail as cloudtrail,
    aws_events_targets as targets,
    aws_glue as glue,
    aws_athena as athena,
    aws_s3_notifications as s3n,
    aws_apigateway as apigateway,
    aws_logs as logs,
    BundlingOptions,
)
from aws_cdk.custom_resources import (
    AwsCustomResource,
    AwsCustomResourcePolicy,
    PhysicalResourceId,
)
import aws_cdk.aws_glue_alpha as glue_alpha


class FeedbackStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # Retrieving application_id, glue_database_name and classification from the context
        self.application_id = self.node.try_get_context("application_id")
        self.classification = self.node.try_get_context("classification")
        self.glue_database_name = self.node.try_get_context("glue_database")

        # bucket to store analytics data.
        self.create_s3_bucket()

        # # create lambda layer
        self.create_lambda_layer()

        # create lambda proxy which will act as proxy for API Gateway
        self.create_api_proxy_lambda()

        # create API Gateway
        self.create_api_gateway()

        # create glue crawler and athena workgroup to analyze the feedback
        self.create_glue_crawler()

        # Code below is optional and is to show how to use the solution to process Qbuiness feedback
        if self.application_id and self.application_id != "":
            # create lambda function to process Q cloudtrail event and invoke API created for logging feedback
            self.create_qbusiness_lambda()

            # create cloudtrail to log Q business events
            self.create_cloudtrail()

    def create_lambda_layer(self):
        # This function creates an AWS Lambda layer containing the boto3 library for Python 3.11.
        # Layers allow sharing common code/dependencies between Lambda functions to avoid duplicating packages.
        self.lambda_layer = _lambda.LayerVersion(
            self,
            "boto_python3_11_layer",
            code=_lambda.AssetCode(
                "lambda_assets/layer/",
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output/python && cp -au . /asset-output/python/common",
                    ],
                ),
            ),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_11],
        )

    def create_s3_bucket(self):
        # The bucket is encrypted using AWS KMS for security.
        # Public access is blocked to prevent unauthorized access to the data.
        # SSL is enforced to encrypt data in transit.
        # The bucket is configured to retain objects on deletion for compliance purposes.
        # A "Classification" tag is added to the bucket to categorize the type of data stored. This helps with data governance and security policies.
        self.data_bucket = s3.Bucket(
            self,
            "chatbot-user-feedback-analytics",
            encryption=s3.BucketEncryption.KMS_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # associating a Classification tag
        Tags.of(self.data_bucket).add("Classification", self.classification)

    def create_api_proxy_lambda(self):

        self.api_proxy_lambda_role = iam.Role(
            self,
            "LambdaLLMAppFeedbackConsumerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        self.api_proxy_lambda_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            )
        )

        self.api_proxy_lambda = _lambda.Function(
            self,
            "llm-app-feedback-processor",
            function_name="llm_app_feedback_processor",
            handler="lambda-handler.lambda_handler",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset("../../../source/llm_app_feedback_processor"),
            timeout=Duration.seconds(240),
            memory_size=256,
            role=self.api_proxy_lambda_role,
            environment={
                "S3_DATA_BUCKET": self.data_bucket.bucket_name,
                "GLUE_DATABASE_NAME": self.glue_database_name,
            },
        )

        # Assigning permissions to the created Lambda function for S3 bucket
        self.data_bucket.grant_write(self.api_proxy_lambda)

    def create_api_gateway(self):

        # Create log group for API Gateway
        self.api_gateway_log_group = logs.LogGroup(
            self,
            "llm-app-feedback-api-log-group",
            log_group_name=f"/aws/apigateway/llm-app-feedback-api",
            removal_policy=RemovalPolicy.DESTROY,
            retention=logs.RetentionDays.ONE_MONTH,
        )

        # Create API Gateway endpoint
        self.api = apigateway.LambdaRestApi(
            self,
            "llm-app-feedback-api",
            handler=self.api_proxy_lambda,
            proxy=False,
            cloud_watch_role=True,
            cloud_watch_role_removal_policy=RemovalPolicy.DESTROY,
            deploy_options=apigateway.StageOptions(
                access_log_destination=apigateway.LogGroupLogDestination(
                    self.api_gateway_log_group
                ),
                access_log_format=apigateway.AccessLogFormat.json_with_standard_fields(
                    caller=True,
                    http_method=True,
                    ip=True,
                    protocol=True,
                    request_time=True,
                    resource_path=True,
                    response_length=True,
                    status=True,
                    user=True,
                ),
                logging_level=apigateway.MethodLoggingLevel.INFO,
            ),
        )

        self.feedback = self.api.root.add_resource("feedback")
        self.post_feedback = self.feedback.add_method(
            "POST",
            authorization_type=apigateway.AuthorizationType.IAM,
        )
        # Outputting the name of the bucket created
        CfnOutput(self, "feedback-data-bucket-name", value=self.data_bucket.bucket_name)

        # Outputting the API Gateway URL
        CfnOutput(self, "API Gateway URL", value=self.api.url)

    def create_glue_crawler(self):
        # Create Glue crawler's IAM role
        self.glue_crawler_role = iam.Role(
            self,
            "GlueCrawlerRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
        )
        self.glue_crawler_role.attach_inline_policy(
            iam.Policy(
                self,
                "glue_crawler_role_policy",
                statements=[
                    iam.PolicyStatement(
                        actions=[
                            "s3:GetBucketLocation",
                            "s3:ListBucket",
                            "s3:GetBucketAcl",
                            "s3:GetObject",
                        ],
                        resources=[f"{self.data_bucket.bucket_arn}/*"],
                    )
                ],
            )
        )

        # Add managed policies to Glue crawler role
        self.glue_crawler_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSGlueServiceRole"
            )
        )

        # Create Glue Database
        glue_database = glue_alpha.Database(
            self, id=self.glue_database_name, database_name=self.glue_database_name
        )

        # Delete the database when deleting the stack
        glue_database.apply_removal_policy(policy=RemovalPolicy.DESTROY)

        self.audit_policy = glue.CfnCrawler.SchemaChangePolicyProperty(
            update_behavior="UPDATE_IN_DATABASE", delete_behavior="LOG"
        )

        self.glue_crawler = glue.CfnCrawler(
            self,
            f"{self.glue_database_name}-crawler",
            name=f"{self.glue_database_name}-crawler",
            role=self.glue_crawler_role.role_arn,
            database_name=self.glue_database_name,
            schedule=glue.CfnCrawler.ScheduleProperty(
                schedule_expression="cron(0 * * * ? *)"
            ),
            targets=glue.CfnCrawler.TargetsProperty(
                s3_targets=[
                    glue.CfnCrawler.S3TargetProperty(
                        path=f"s3://{self.data_bucket.bucket_name}/{self.glue_database_name}/feedback/",
                        exclusions=["Unsaved", "athena_query_result/**"],
                        sample_size=100,
                    )
                ]
            ),
        )

        # Create an Athena work group CloudFormation resource
        athena_work_group = athena.CfnWorkGroup(
            self,
            id="AthenaWorkGroupAthenaID",
            name="AI-ChatbotFeedback-WorkGroup",
            description="Run athena queries for chatbot user feedback",
            recursive_delete_option=True,
            state="ENABLED",
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                # Publish metrics to CloudWatch
                publish_cloud_watch_metrics_enabled=True,
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    # Encrypt results using SSE-S3
                    encryption_configuration=athena.CfnWorkGroup.EncryptionConfigurationProperty(
                        encryption_option="SSE_S3"
                    ),
                    # Location in S3 bucket for query results
                    output_location=f"s3://{self.data_bucket.bucket_name}/athena_query_result/",
                ),
            ),
        )

    def create_qbusiness_lambda(self):
        # Defining an IAM policy for the Business Q service with necessary permissions
        policy_statement_q = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["qbusiness:ListMessages"],
            resources=[
                f"arn:aws:qbusiness:{Aws.REGION}:{Aws.ACCOUNT_ID}:application/{self.application_id}"
            ],
        )
        # Define an IAM policy to invoke the API Gateway
        policy_statement_api = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["execute-api:Invoke"],
            resources=[self.post_feedback.method_arn],
        )
        # Add IAM authentication to API Gateway

        # Creating an IAM role for the Lambda
        self.qbusiness_lambda_role = iam.Role(
            self,
            "LambdaBusinessQConsumerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        self.qbusiness_lambda_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            )
        )
        # Defining and deploying a Lambda function
        self.qbusiness_feedback_processor = _lambda.Function(
            self,
            "businessq-feedback-processor",
            function_name="businessq_feedback_processor",
            handler="lambda-handler.lambda_handler",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset("../../../source/businessq_feedback_processor"),
            timeout=Duration.seconds(240),
            memory_size=256,
            role=self.qbusiness_lambda_role,
            environment={"API_GATEWAY_URL": self.api.url_for_path(self.feedback.path)},
            layers=[self.lambda_layer],
        )
        self.qbusiness_feedback_processor.add_to_role_policy(policy_statement_q)
        self.qbusiness_feedback_processor.add_to_role_policy(policy_statement_api)

        # Assigning permissions to the created Lambda function for S3 bucket
        self.data_bucket.grant_write(self.qbusiness_feedback_processor)

    def create_cloudtrail(self):
        # Setting up a CloudTrail 'trail' and sending its logs to CloudWatch
        self.trail = cloudtrail.Trail(
            self,
            "BusinessQCloudTrail",
            trail_name="BusinessQCloudTrail",
        )

        # Setting up an EventRule to trigger lambda function on certain conditions
        event_rule = cloudtrail.Trail.on_event(
            self,
            "BusinessQCloudWatchEvent",
            target=targets.LambdaFunction(self.qbusiness_feedback_processor),
        )

        event_rule.add_event_pattern(
            source=["aws.qbusiness"],
            detail_type=["AWS API Call via CloudTrail"],
            detail={
                "eventSource": ["qbusiness.amazonaws.com"],
                "eventName": ["PutFeedback"],
            },
        )

        # Attaching custom advanced event selectors to the CloudTrail 'trail'
        event_selectors = [
            {
                "Name": "Log all data events on an Amazon Q application",
                "FieldSelectors": [
                    {"Field": "eventCategory", "Equals": ["Data"]},
                    {
                        "Field": "resources.type",
                        "Equals": ["AWS::QBusiness::Application"],
                    },
                ],
            },
            {
                "Name": "Log all data events on an Amazon Q data source",
                "FieldSelectors": [
                    {"Field": "eventCategory", "Equals": ["Data"]},
                    {
                        "Field": "resources.type",
                        "Equals": ["AWS::QBusiness::DataSource"],
                    },
                ],
            },
            {
                "Name": "Log all data events on an Amazon Q index",
                "FieldSelectors": [
                    {"Field": "eventCategory", "Equals": ["Data"]},
                    {"Field": "resources.type", "Equals": ["AWS::QBusiness::Index"]},
                ],
            },
        ]

        # cloudtrail data events for Business Q
        cloudtrail_put_event_selectors = AwsCustomResource(
            self,
            id="CloudTrailPutEventSelectors",
            # log_retention=RetentionDays.ONE_WEEK,
            on_create={
                "service": "CloudTrail",
                "action": "putEventSelectors",
                "parameters": {
                    "TrailName": self.trail.trail_arn,
                    "AdvancedEventSelectors": event_selectors,
                },
                "physical_resource_id": PhysicalResourceId.of(
                    "cloudtrail_" + strftime("%Y%m%d%H%M%S")
                ),
            },
            policy=AwsCustomResourcePolicy.from_sdk_calls(
                resources=[
                    f"arn:aws:cloudtrail:{Aws.REGION}:{Aws.ACCOUNT_ID}:trail/BusinessQCloudTrail"
                ]
            ),
        )
