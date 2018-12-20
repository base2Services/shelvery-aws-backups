import boto3
import os
import json
import logging

from typing import Dict
from threading import Thread

from shelvery.runtime_config import RuntimeConfig
from shelvery.aws_helper import AwsHelper
from shelvery.queue import ShelveryQueue

class ShelveryInvoker:
    """Helper to orchestrate execution of shelvery operations on AWS Lambda platform"""

    def invoke_shelvery_operation(self, engine, method_name: str, method_arguments: Dict):
        """
        Invokes shelvery engine asynchronously
        If shelvery is running within lambda environment, new lambda function invocation will be made. If running
        on server, it will start new thread and invoke the function
        Function invoke must accept arguments in form of map
        """
        is_lambda_context = RuntimeConfig.is_lambda_runtime(engine)
        is_offload_queueing = RuntimeConfig.is_offload_queueing(engine)
        parameters = {
            'backup_type': engine.get_engine_type(),
            'action': method_name,
            'arguments': method_arguments
        }
        if is_lambda_context:
            if 'config' in engine.lambda_payload:
                parameters['config'] = engine.lambda_payload['config']

            if is_offload_queueing:
                sqs = ShelveryQueue(RuntimeConfig.get_sqs_queue_url(engine),RuntimeConfig.get_sqs_queue_wait_period(engine))
                sqs.send(parameters)
            else:
                parameters['is_started_internally'] = True
                payload = json.dumps(parameters)
                bytes_payload = bytearray()
                bytes_payload.extend(map(ord, payload))
                function_name = os.environ['AWS_LAMBDA_FUNCTION_NAME']
                lambda_client = AwsHelper.boto3_client('lambda')
                lambda_client.invoke_async(FunctionName=function_name, InvokeArgs=bytes_payload)
        else:
            resource_type = engine.get_engine_type()

            def execute():
                from shelvery.factory import ShelveryFactory
                backup_engine = ShelveryFactory.get_shelvery_instance(resource_type)
                method = backup_engine.__getattribute__(method_name)
                method(method_arguments)

            logging.info(f"Start new thread to execute :{method_name}")
            if 'SHELVERY_MONO_THREAD' in os.environ and os.environ['SHELVERY_MONO_THREAD'] == "1":
                execute()
            else:
                thread = Thread(target=execute)
                thread.start()
            # thread.join()
