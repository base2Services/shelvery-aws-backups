from datetime import datetime
from typing import Dict
import boto3


class EntityResource:
    """Represents entity such as ec2 volume, instance or rds instance"""
    
    def __init__(self, resource_id: str, resource_region: str, date_created: datetime, tags: Dict):
        self.resource_id = resource_id
        self.date_created = date_created
        self.tags = tags
        self.resource_region = resource_region
    
    @classmethod
    def empty(cls):
        local_region = boto3.session.Session().region_name
        resource = EntityResource(None, local_region, None, {})
        return resource
