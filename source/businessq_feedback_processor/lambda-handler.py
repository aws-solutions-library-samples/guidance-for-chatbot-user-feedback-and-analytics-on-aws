import boto3
import json
import logging
from urllib.parse import urlparse
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from botocore.exceptions import ClientError
import requests
from aws_requests_auth.boto_utils import BotoAWSRequestsAuth


logger = logging.getLogger()
logger.setLevel(logging.ERROR)

api_gateway_url = os.environ['API_GATEWAY_URL']

auth = BotoAWSRequestsAuth(aws_host=urlparse(api_gateway_url).hostname,
                           aws_region=os.environ['AWS_REGION'],
                           aws_service='execute-api')

# Business Q client
client = boto3.client('qbusiness')

        
def extract_urls_from_json(data):
    urls = []
    try:
        data = json.loads(data)
        for item in data:
            urls.append(item['url'])
    except Exception as e:
        print(f"An error occurred: {e}")
    return urls
    

def lambda_handler(event, context):
    
    messageId = str(event["detail"]["requestParameters"]["messageId"])
    applicationId = event["detail"]["requestParameters"]["applicationId"]
    usefulness = event["detail"]["requestParameters"]["messageUsefulness"]['usefulness']
    submittedAt = event["detail"]["requestParameters"]["messageUsefulness"]['submittedAt']
    userId = event["detail"]["userIdentity"]["onBehalfOf"]["userId"]

    # with thumbs down there are comments sometimes
    try:
        usefulness_comment = event["detail"]["requestParameters"]["messageUsefulness"]['comment']
    except KeyError:
        usefulness_comment = ""

    # Add message details to the analytics data
    response_data = json.dumps({
        'interactionId': messageId,
        'appIdentifier': applicationId,
        'feedback': usefulness,
        'comment': usefulness_comment,
        'userId': userId,
        'submittedAt': submittedAt
    })
            
    # create json response payload
    logger.info(response_data)
    
    # invoke api gateway url and make a post request with request data as body
    logger.info(api_gateway_url)
    
    logger.debug("Posting feedback to api endpoint for message: " + messageId)
    
    # send post request to api gateway url with request data as body
    response = requests.post(api_gateway_url, data=response_data,auth=auth)

    return {
        'statusCode': 200,
        'body': response_data
    }