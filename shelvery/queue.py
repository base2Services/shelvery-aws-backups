import boto3
import json
import logging
from shelvery.aws_helper import AwsHelper
from datetime import datetime

logger = logging.getLogger(__name__)


class ShelveryQueue:

    def __init__(self, queue_url, wait_period):
        self.queue_url = queue_url
        # Max wait time is 900, if is set to greater, set value to 900
        self.wait_period = int(wait_period) if int(wait_period) < 900 else 900
        logger.info(f"Initialized sqs service with message delay of {self.wait_period} seconds")
        self.sqs = AwsHelper.boto3_client('sqs')

    def send(self, message):
        if isinstance(message, dict):
            message['Timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
            message = json.dumps(message)

        if self.queue_url is not None:
            try:
                response = self.sqs.send_message(
                    QueueUrl=self.queue_url,
                    DelaySeconds=self.wait_period,
                    MessageBody=message
                )
            except:
                logger.exception('Failed to send message to sqs queue')
                logger.error(f"Message:{message}")
