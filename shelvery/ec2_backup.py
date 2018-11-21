import boto3

from shelvery.backup_resource import BackupResource
from shelvery.engine import ShelveryEngine
from shelvery.entity_resource import EntityResource
from shelvery.aws_helper import AwsHelper
from typing import Dict, List


class ShelveryEC2Backup(ShelveryEngine):
    """Parent class sharing common functionality for AMI and EBS backups"""

    def __init__(self):
        ShelveryEngine.__init__(self)
        # default region will be picked up in AwsHelper.boto3_client call
        self.region = boto3.session.Session().region_name

    def tag_backup_resource(self, backup_resource: BackupResource):
        regional_client = AwsHelper.boto3_client('ec2', region_name=backup_resource.region, arn=self.role_arn, external_id=self.role_external_id)
        regional_client.create_tags(
            Resources=[backup_resource.backup_id],
            Tags=list(map(lambda k: {'Key': k, 'Value': backup_resource.tags[k]}, backup_resource.tags))
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

    def is_backup_available(self, backup_region: str, backup_id: str) -> bool:
        pass

    def copy_backup_to_region(self, backup_id: str, region: str) -> str:
        pass

    def get_backup_resource(self, region: str, backup_id: str) -> BackupResource:
        pass

    def share_backup_with_account(self, backup_region: str, backup_id: str, aws_account_id: str):
        pass
