import boto3

from shelvery.backup_resource import BackupResource
from shelvery.engine import ShelveryEngine
from shelvery.entity_resource import EntityResource

from typing import Dict, List


class ShelveryEC2Backup(ShelveryEngine):
    """Parent class sharing common functionality for AMI and EBS backups"""

    def __init__(self):
        ShelveryEngine.__init__(self)
        self.ec2client = boto3.client('ec2')
    
    def tag_backup_resource(self, backup_resource_id: str, tags: Dict):
        self.ec2client.create_tags(
            Resources=[backup_resource_id],
            Tags=list(map(lambda k: {'Key': k, 'Value': tags[k]}, tags))
        )

    def delete_backup(self, backup_resource: BackupResource):
        pass

    def get_existing_backups(self, backup_tag_prefix: str) -> List[BackupResource]:
        pass

    def get_resource_type(self) -> str:
        pass

    def backup_resource(self, backup_resource: BackupResource):
        pass

    def get_entities_to_backup(self, tag_name: str) -> List[EntityResource]:
        pass
