import boto3
import os

from typing import Dict


class ShelveryLambdaHelper:
    """Helper to orchestrate execution of shelvery utility on AWS Lambda platform"""
    
    def __init__(self):
        self.lambda_client = boto3.client('lambda')
    
    def invoke_shelvery(self, engine_name: str, method_name: str, method_arguments: Dict):
        method_arguments['is_started_internally'] = True
        payload = {
            'backup_type': engine_name,
            'action': method_name,
            'arguments': method_arguments
        }
        function_name = os.environ['AWS_LAMBDA_FUNCTION_NAME']
        self.lambda_client.invoke_async(FunctionName=function_name, InvokeArgs=payload)
