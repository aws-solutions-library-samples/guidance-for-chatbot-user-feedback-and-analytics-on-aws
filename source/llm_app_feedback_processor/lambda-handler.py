import boto3
import json
import logging
import os
import uuid
from datetime import datetime


logger = logging.getLogger()
logger.setLevel(logging.ERROR)

# S3 client
s3 = boto3.client('s3')

# sink the feedback json to the s3 bucket
s3_bucket = os.environ['S3_DATA_BUCKET']
glue_database_name = os.environ['GLUE_DATABASE_NAME']


    

def lambda_handler(event, context):
    error_response = """{{
        "statusCode": 400,
        "headers": {{
            "Content-Type": "*/*"
            }},
        "body": "Error: parameter {param} is a required parameter"
    }}"""
    if (event['body']) and (event['body'] is not None):
        body = json.loads(event['body'])
        try:
            prompt = body['prompt']
        except KeyError:
            prompt = "N.A."
            logger.warning("prompt is missing in the request body")
        
        try:
            response = body['response']
        except KeyError:
            response = "N.A."
            logger.warning("response is missing in the request body")

        try:
            feedback = body['feedback']
        except KeyError:
            logger.error("feedback is missing in the request body")
            error_response = error_response.format(param="feedback")
            return json.loads(error_response)
        
        try:
            userId = body['userId']        
        except KeyError:            
            logger.error("userId is missing in the request body")
            error_response = error_response.format(param="userId")
            return json.loads(error_response)
        
        try:            
            appIdentifier = body['appIdentifier']
        except KeyError:
            logger.error("appIdentifier is missing in the request body")
            error_response = error_response.format(param="appIdentifier")
            return json.loads(error_response)

        try:
            interactionId = body['interactionId']
        except KeyError:
            logger.warning("interactionId is missing in the request body")
            interactionId=str(uuid.uuid4())            
        
        try:
            comment = body['comment']
        
        except KeyError:
            logger.info("comment is a missing in the request body")
            comment = ""

        try:
            sourceAttribution = body['sourceAttribution']
            logger.info(sourceAttribution)
        except KeyError:
            logger.warning("sourceAttribution is a missing in the request body")
            sourceAttribution = ""
    
        try:
            source_attribution_urls = body['sourceUrls']
            logger.info(source_attribution_urls)
        
        except KeyError:
            logger.warning("sourceUrls is a missing in the request body")
            source_attribution_urls = []

        try:
            submittedAt = body['submittedAt']
            logger.info(submittedAt)
        except KeyError:
            current_date = datetime.now()
            submittedAt = current_date.strftime("%b %d, %Y, %I:%M:%S %p")
    else:
        return {
            'statusCode': 400,
            'body': 'Error: request body is missing'
        }
        
    response_data = json.dumps({
            'interactionId': interactionId,
            'prompt': prompt,
            'response': response,
            'source_attribution_urls': source_attribution_urls,
            'sourceAttribution': sourceAttribution,
            'appIdentifier': appIdentifier,
            'feedback': feedback,
            'comment':   comment,
            'userId': userId,
            'submittedAt': submittedAt
        })           
    current_date = datetime.now()
    key = f'{glue_database_name}/feedback/year={current_date.year}/month={current_date.strftime("%m")}/day={current_date.strftime("%d")}/{interactionId}.json'
    
    bucket_name = s3_bucket
    s3.put_object(Body=response_data, Bucket=bucket_name, Key=key)
    
    # Return the JSON response
    return {
        'statusCode': 200,
        'body': response_data
    }