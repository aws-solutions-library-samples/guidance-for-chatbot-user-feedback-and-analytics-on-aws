#!/usr/bin/env python3
import os

from aws_cdk import App, Tags,Aspects,Environment,Aws
from ai_chatbot_feedback_analytics.feedback_stack import FeedbackStack
from cdk_nag import AwsSolutionsChecks, NagSuppressions

app = App()


qlambda = FeedbackStack(app, "ai-chatbot-feedback-analytics-stack", description='Feedback collection for GenAI chatbot (SO9465)')
Tags.of(qlambda).add("project", "feedback-analytics-stack")

NagSuppressions.add_stack_suppressions(
    qlambda,
    [
        {
            "id": "AwsSolutions-S1",
            "reason": "S3 Access Logs are disabled for demo purposes.",
        },
        {
            "id": "AwsSolutions-L1",
            "reason": "Boto version requires python 3.11",
        },

        {
            "id": "AwsSolutions-IAM4",
            "reason": "Use Lambda managed policy with Lambda for custom policies. ",
        },
        {
            "id": "AwsSolutions-IAM5",
            "reason": "Using CDK S3 grant write permissions.",
        },
        {
            "id": "AwsSolutions-SQS3",
            "reason": "DLQ not used for Glue crawler for sample.",
        },
        {
            "id": "AwsSolutions-ATH1",
            "reason": " Athena workgroup uses SSE_S3 encryption.",
        },
        {
            "id": "AwsSolutions-COG4",
            "reason": "API GW method is using IAM autorizer",
        },
        {
            "id": "AwsSolutions-APIG2",
            "reason": "Request body is validated in lambda function",
        }
    ],
)

Aspects.of(app).add(AwsSolutionsChecks())

app.synth()
