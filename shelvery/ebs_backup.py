import boto3

from typing import List

from botocore.exceptions import ClientError
from shelvery.aws_helper import AwsHelper
from shelvery.engine import SHELVERY_DO_BACKUP_TAGS
from shelvery.ec2_backup import ShelveryEC2Backup
from shelvery.entity_resource import EntityResource
from shelvery.backup_resource import BackupResource


class ShelveryEBSBackup(ShelveryEC2Backup):
    """Shelvery engine implementation for EBS data backups"""

    def __init__(self):
        ShelveryEC2Backup.__init__(self)

    def delete_backup(self, backup_resource: BackupResource):
        ec2client = AwsHelper.boto3_client('ec2', arn=self.role_arn, external_id=self.role_external_id)
        ec2client.delete_snapshot(SnapshotId=backup_resource.backup_id)

    def get_existing_backups(self, tag_prefix: str) -> List[BackupResource]:
        ec2client = AwsHelper.boto3_client('ec2', arn=self.role_arn, external_id=self.role_external_id)
        # lookup snapshots by tags
        snapshots = ec2client.describe_snapshots(Filters=[
            {'Name': f"tag:{tag_prefix}:{BackupResource.BACKUP_MARKER_TAG}", 'Values': ['true']}
        ])
        backups = []

        # create backup resource objects
        for snap in snapshots['Snapshots']:
            backup = BackupResource.construct(
                tag_prefix=tag_prefix,
                backup_id=snap['SnapshotId'],
                tags=dict(map(lambda t: (t['Key'], t['Value']), snap['Tags']))
            )
            # legacy code - entity id should be picked up from tags
            if backup.entity_id is None:
                backup.entity_id = snap['VolumeId']
            backups.append(backup)

        self.populate_volume_information(backups)

        return backups

    def get_engine_type(self) -> str:
        return 'ebs'

    def get_resource_type(self) -> str:
        return 'ec2 volume'

    def backup_resource(self, backup_resource: BackupResource) -> BackupResource:
        ec2client = AwsHelper.boto3_client('ec2', arn=self.role_arn, external_id=self.role_external_id)
        # create snapshot
        snap = ec2client.create_snapshot(
            VolumeId=backup_resource.entity_id,
            Description=backup_resource.name
        )
        backup_resource.backup_id = snap['SnapshotId']
        return backup_resource

    def get_backup_resource(self, region: str, backup_id: str) -> BackupResource:
        ec2 = AwsHelper.boto3_session('ec2', region_name=region, arn=self.role_arn, external_id=self.role_external_id)
        snapshot = ec2.Snapshot(backup_id)
        d_tags = dict(map(lambda t: (t['Key'], t['Value']), snapshot.tags))
        return BackupResource.construct(d_tags['shelvery:tag_name'], backup_id, d_tags)

    def get_entities_to_backup(self, tag_name: str) -> List[EntityResource]:
        volumes = self.collect_volumes(tag_name)
        return list(
            map(
                lambda vol: EntityResource(
                    resource_id=vol['VolumeId'],
                    resource_region=self.region,
                    date_created=vol['CreateTime'],
                    tags=dict(map(lambda t: (t['Key'], t['Value']), vol['Tags']))
                ),
                volumes
            )
        )

    def is_backup_available(self, region: str, backup_id: str) -> bool:
        try:
            regional_client = AwsHelper.boto3_client('ec2', region_name=region, arn=self.role_arn, external_id=self.role_external_id)
            snapshot = regional_client.describe_snapshots(SnapshotIds=[backup_id])['Snapshots'][0]
            complete = snapshot['State'] == 'completed'
            self.logger.info(f"{backup_id} is {snapshot['Progress']} complete")
            return complete
        except Exception as e:
            self.logger.warn(f"Problem getting status of ec2 snapshot status for snapshot {backup_id}:{e}")

    def copy_backup_to_region(self, backup_id: str, region: str):
        ec2client = AwsHelper.boto3_client('ec2', arn=self.role_arn, external_id=self.role_external_id)
        snapshot = ec2client.describe_snapshots(SnapshotIds=[backup_id])['Snapshots'][0]
        regional_client = AwsHelper.boto3_client('ec2', region_name=region, arn=self.role_arn, external_id=self.role_external_id)
        copy_snapshot_response = regional_client.copy_snapshot(SourceSnapshotId=backup_id,
                                                               SourceRegion=ec2client._client_config.region_name,
                                                               DestinationRegion=region,
                                                               Description=snapshot['Description'])

        # return id of newly created snapshot in dr region
        return copy_snapshot_response['SnapshotId']

    def share_backup_with_account(self, backup_region: str, backup_id: str, aws_account_id: str):
        ec2 = AwsHelper.boto3_session('ec2', region_name=backup_region, arn=self.role_arn, external_id=self.role_external_id)
        snapshot = ec2.Snapshot(backup_id)
        snapshot.modify_attribute(Attribute='createVolumePermission',
                                  CreateVolumePermission={
                                      'Add': [{'UserId': aws_account_id}]
                                  },
                                  UserIds=[aws_account_id],
                                  OperationType='add')

    def copy_shared_backup(self, source_account: str, source_backup: BackupResource):
        ec2client = AwsHelper.boto3_client('ec2', arn=self.role_arn, external_id=self.role_external_id)
        snap = ec2client.copy_snapshot(
            SourceSnapshotId=source_backup.backup_id,
            SourceRegion=source_backup.region
        )
        return snap['SnapshotId']
    # collect all volumes tagged with given tag, in paginated manner
    def collect_volumes(self, tag_name: str):
        load_volumes = True
        next_token = ''
        all_volumes = []
        ec2client = AwsHelper.boto3_client('ec2', arn=self.role_arn, external_id=self.role_external_id)
        while load_volumes:
            tagged_volumes = ec2client.describe_volumes(
                Filters=[{'Name': f"tag:{tag_name}", 'Values': SHELVERY_DO_BACKUP_TAGS}],
                NextToken=next_token
            )
            all_volumes = all_volumes + tagged_volumes['Volumes']
            if 'NextToken' in tagged_volumes and len(tagged_volumes['NextToken']) > 0:
                load_volumes = True
                next_token = tagged_volumes['NextToken']
            else:
                load_volumes = False

        return all_volumes

    def populate_volume_information(self, backups):
        volume_ids = []
        volumes = {}
        ec2client = AwsHelper.boto3_client('ec2', arn=self.role_arn, external_id=self.role_external_id)
        local_region = boto3.session.Session().region_name

        # create list of all volume ids
        for backup in backups:
            if backup.entity_id not in volume_ids:
                volume_ids.append(backup.entity_id)

        # populate map volumeid->volume if present
        for volume_id in volume_ids:
            try:
                volume = ec2client.describe_volumes(VolumeIds=[volume_id])['Volumes'][0]
                d_tags = dict(map(lambda t: (t['Key'], t['Value']), volume['Tags']))
                volumes[volume_id] = EntityResource(volume_id, local_region, volume['CreateTime'], d_tags)
            except ClientError as e:
                if 'InvalidVolume.NotFound' in str(e):
                    volumes[volume_id] = EntityResource.empty()
                    volumes[volume_id].resource_id = volume_id
                else:
                    raise e

        # add info to backup resource objects
        for backup in backups:
            if backup.entity_id in volumes:
                backup.entity_resource = volumes[backup.entity_id]
