import boto3
import os
import json
import logging

from typing import Dict
from threading import Thread

from shelvery.runtime_config import RuntimeConfig


class ShelveryInvoker:
    """Helper to orchestrate execution of shelvery operations on AWS Lambda platform"""
    
    def __init__(self):
        self.lambda_client = boto3.client('lambda')
    
    def invoke_shelvery_operation(self, engine, method_name: str, method_arguments: Dict):
        """
        Invokes shelvery engine asynchronously
        If shelvery is running within lambda environment, new lambda function invocation will be made. If running
        on server, it will start new thread and invoke the function
        Function invoke must accept arguments in form of map
        """
        is_lambda_context = RuntimeConfig.is_lambda_runtime(engine)
        parameters = {
            'backup_type': engine.get_engine_type(),
            'action': method_name,
            'arguments': method_arguments
        }
        if is_lambda_context:
            parameters['is_started_internally'] = True
            if 'config' in engine.lambda_payload:
                parameters['config'] = engine.lambda_payload['config']
            payload = json.dumps(parameters)
            bytes_payload = bytearray()
            bytes_payload.extend(map(ord, payload))
            function_name = os.environ['AWS_LAMBDA_FUNCTION_NAME']
            self.lambda_client.invoke_async(FunctionName=function_name, InvokeArgs=bytes_payload)
        else:
            resource_type = engine.get_engine_type()
            
            def execute():
                from shelvery.factory import ShelveryFactory
                backup_engine = ShelveryFactory.get_shelvery_instance(resource_type)
                method = backup_engine.__getattribute__(method_name)
                method(method_arguments)
                
            logging.info(f"Start new thread to execute :{method_name}")
            thread = Thread(target=execute)
            thread.start()
            # thread.join()
