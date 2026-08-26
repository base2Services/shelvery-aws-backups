import boto3
import json
import logging
from shelvery.aws_helper import AwsHelper
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ShelveryNotification:
    
    def __init__(self, topic_arn):
        self.topic_arn = topic_arn
        logger.info("Initialized notification service")
        self.sns = AwsHelper.boto3_client('sns')
    
    def notify(self, message, subject=None):
        if self.topic_arn is None or not self.topic_arn.startswith('arn:aws:sns'):
            return

        try:
            if isinstance(message, dict):
                message['Timestamp'] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                # default=str so a value that isn't JSON serializable degrades to its repr
                # rather than raising - notify() is called from within except blocks, and a
                # raise here would turn a handled per-resource failure into a whole-run abort
                message = json.dumps(message, default=str)

            params = {'TopicArn': self.topic_arn, 'Message': message}
            if subject is not None:
                params['Subject'] = subject[:100]

            self.sns.publish(**params)
        except Exception:
            logger.exception('Failed publishing to SNS Topic')
            logger.error(f"Message:{message}")
