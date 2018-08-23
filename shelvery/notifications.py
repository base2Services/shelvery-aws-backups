import boto3
import json
import logging

from datetime import datetime

logger = logging.getLogger(__name__)


class ShelveryNotification:
    
    def __init__(self, topic_arn):
        self.topic_arn = topic_arn
        logger.info("Initialized notification service")
        self.sns = boto3.client('sns')
    
    def notify(self, message):
        if isinstance(message, dict):
            message['Timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
            message = json.dumps(message)
        
        if self.topic_arn is not None and self.topic_arn.startswith('arn:aws:sns'):
            try:
                self.sns.publish(
                    TopicArn=self.topic_arn,
                    Message=message
                )
            except:
                logger.exception('Failed publishing to SNS Topic')
                logger.error(f"Message:{message}")
