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
logger.setLevel(logging.INFO)

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
    userId = event["detail"]["requestParameters"]['userId']

    response = client.list_messages(
        applicationId=event["detail"]["requestParameters"]["applicationId"],
        conversationId=event["detail"]["requestParameters"]["conversationId"],
        maxResults=10,
        userId=event["detail"]["requestParameters"]['userId']
    )
    messages = response['messages']
    
    # with thumbs down there are comments sometimes
    try:
        usefulness_comment = event["detail"]["requestParameters"]["messageUsefulness"]['comment']
    except KeyError:
        usefulness_comment = ""

    
    source_attribution_urls = []
    
    logger.info("All Messages")
    logger.info(messages)
    response_data = ""

    # Find the index of the message, this will be the message corresponding to user query
    message_index = [i for i, message in enumerate(messages) if message['messageId'] == messageId][0]            
    query = messages[message_index]['body']
            
    # get the message before to get the AI response
    previous_message_index = message_index - 1
    generated_response = messages[previous_message_index]['body']
    try:
        source_attribution = messages[previous_message_index]['sourceAttribution']
    except KeyError:
        source_attribution = None    
    logger.info("debug 0")
            
    # check if previous_body_source_attribution is not None
    if source_attribution is not None:
        # get the sourceattribute urls from citations and add to a list
        source_attribution_urls = extract_urls_from_json(json.dumps(source_attribution))

    logger.info("debug 1")
    # Add message details to the analytics data
    response_data = json.dumps({
        'interactionId': messageId,
        'prompt': query,
        'response': generated_response,
        'source_attribution_urls': source_attribution_urls,
        'sourceAttribution': source_attribution,
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
    
    logger.debug("posting feedback to api endpoint")
    # send post request to api gateway url with request data as body
    response = requests.post(api_gateway_url, data=response_data,auth=auth)
    
    logger.info(f"response: {response.text}")
    # logger.info(response.text)

    return {
        'statusCode': 200,
        'body': response_data
    }