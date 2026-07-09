import boto3
import yaml

from typing import Dict, List, Tuple

from botocore.exceptions import ClientError
from shelvery.aws_helper import AwsHelper
from shelvery.engine import SHELVERY_DO_BACKUP_TAGS
from shelvery.ec2_backup import ShelveryEC2Backup
from shelvery.entity_resource import EntityResource
from shelvery.backup_resource import BackupResource
from shelvery.runtime_config import RuntimeConfig
from shelvery import S3_DATA_PREFIX


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
            snap_tags = dict(map(lambda t: (t['Key'], t['Value']), snap['Tags']))
            if f"{tag_prefix}:ami_id" in snap_tags:
                self.logger.info(f"EBS snapshot {snap['SnapshotId']} created by AMI shelvery backup, skiping...")
                continue
                            
            backup = BackupResource.construct(
                tag_prefix=tag_prefix,
                backup_id=snap['SnapshotId'],
                tags=snap_tags
            )
            # legacy code - entity id should be picked up from tags
            if backup.entity_id is None:
                self.logger.info(f"SnapshotId is None, using VolumeId {snap['VolumeId']}")
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

    def archive_backup(self, backup_resource: BackupResource):
        """Move snapshot to the EBS Snapshots Archive tier for long-term storage."""
        ec2client = AwsHelper.boto3_client('ec2', arn=self.role_arn, external_id=self.role_external_id)
        ec2client.modify_snapshot_tier(
            SnapshotId=backup_resource.backup_id,
            StorageTier='archive'
        )
        self.logger.info(f"Initiated archive of snapshot {backup_resource.backup_id}")

    def _config_tags_from_backup(self, backup_resource: BackupResource) -> Dict[str, str]:
        tags = backup_resource.entity_resource_tags()
        if tags:
            return tags
        tag_prefix = backup_resource.tags.get('shelvery:tag_name', RuntimeConfig.get_tag_prefix())
        config_tags = {}
        for key, value in backup_resource.tags.items():
            if key.startswith(f"{tag_prefix}:config:"):
                config_tags[f"shelvery:config:{key.split(':config:', 1)[1]}"] = value
            elif key.startswith('shelvery:config:'):
                config_tags[key] = value
        return config_tags

    def _is_monthly_or_yearly(self, backup_resource: BackupResource) -> bool:
        return backup_resource.retention_type in [
            BackupResource.RETENTION_MONTHLY,
            BackupResource.RETENTION_YEARLY,
        ]

    def _should_archive_source(self, backup_resource: BackupResource) -> bool:
        tags = self._config_tags_from_backup(backup_resource)
        return (RuntimeConfig.get_enable_ebs_archive(tags or None, self)
                and self._is_monthly_or_yearly(backup_resource))

    def _should_archive_pulled(self, backup_resource: BackupResource) -> bool:
        tags = self._config_tags_from_backup(backup_resource)
        return (RuntimeConfig.get_enable_ebs_archive_pulled(tags or None, self)
                and self._is_monthly_or_yearly(backup_resource))

    def _snapshot_is_standard_tier(self, backup_resource: BackupResource) -> bool:
        try:
            regional_client = AwsHelper.boto3_client(
                'ec2',
                region_name=backup_resource.region,
                arn=self.role_arn,
                external_id=self.role_external_id,
            )
            snapshot = regional_client.describe_snapshots(
                SnapshotIds=[backup_resource.backup_id]
            )['Snapshots'][0]
            return snapshot.get('StorageTier', 'standard') == 'standard'
        except Exception as e:
            self.logger.warn(
                f"Could not determine storage tier for snapshot {backup_resource.backup_id}: {e}"
            )
            return False

    def archive_pending_backups(self):
        """Archive source-account snapshots after all share targets have pulled them.

        When no share accounts are configured, archives eligible local snapshots directly.
        """
        if not RuntimeConfig.get_enable_ebs_archive(None, self):
            self.logger.info("EBS source archive disabled, skipping archive_pending_backups")
            return

        share_accounts = RuntimeConfig.get_share_with_accounts(self)
        if not share_accounts:
            self._archive_standalone_backups()
            return

        bucket = self._get_data_bucket()
        bucket_name = bucket.name
        regional_client = self._get_s3_regional_client(bucket_name)
        engine_type = self.get_engine_type()

        ready_backups = self._collect_backups_ready_for_source_archive(
            share_accounts, bucket_name, regional_client, engine_type
        )

        for backup, accounts_with_processed in ready_backups:
            self._archive_source_backup_if_eligible(
                backup, accounts_with_processed, bucket_name, regional_client
            )

    def post_pull_backups(self, backup_resources):
        """Archive pulled copies in the databunker account when enabled."""
        for backup in backup_resources:
            if not self._should_archive_pulled(backup):
                continue
            try:
                self.wait_backup_available(backup.region, backup.backup_id, None, None)
                self.archive_backup(backup)
            except Exception as e:
                self.logger.exception(f"Failed to archive pulled snapshot {backup.backup_id}: {e}")

    def _archive_standalone_backups(self):
        tag_prefix = RuntimeConfig.get_tag_prefix()
        for backup in self.get_existing_backups(tag_prefix):
            if not self._should_archive_source(backup):
                continue
            if not self._snapshot_is_standard_tier(backup):
                continue
            try:
                self.wait_backup_available(backup.region, backup.backup_id, None, None)
                self.archive_backup(backup)
            except Exception as e:
                self.logger.exception(f"Failed to archive snapshot {backup.backup_id}: {e}")

    def _collect_backups_ready_for_source_archive(
        self,
        share_accounts: List[str],
        bucket_name: str,
        regional_client,
        engine_type: str,
    ) -> List[Tuple[BackupResource, Dict[str, str]]]:
        processed_by_name: Dict[str, Dict[str, str]] = {}

        for dest_account in share_accounts:
            path_processed = f"{S3_DATA_PREFIX}/shared/{dest_account}/{engine_type}-processed/"
            path_archived = f"{S3_DATA_PREFIX}/shared/{dest_account}/{engine_type}-archived/"

            for obj in self._list_s3_objects(regional_client, bucket_name, path_processed):
                name = self._backup_name_from_s3_key(obj['Key'])
                archived_key = f"{path_archived}{name}.yaml"
                if self._s3_object_exists(regional_client, bucket_name, archived_key):
                    continue
                if name not in processed_by_name:
                    processed_by_name[name] = {}
                processed_by_name[name][dest_account] = obj['Key']

        ready = []
        share_account_set = set(share_accounts)
        for name, accounts_with_processed in processed_by_name.items():
            if set(accounts_with_processed.keys()) == share_account_set:
                processed_key = next(iter(accounts_with_processed.values()))
                backup = self._load_backup_from_s3(regional_client, bucket_name, processed_key)
                ready.append((backup, accounts_with_processed))

        return ready

    def _archive_source_backup_if_eligible(
        self,
        backup: BackupResource,
        accounts_with_processed: Dict[str, str],
        bucket_name: str,
        regional_client,
    ):
        if not self._should_archive_source(backup):
            return
        if not self._snapshot_is_standard_tier(backup):
            return
        try:
            self.wait_backup_available(backup.region, backup.backup_id, None, None)
            self.archive_backup(backup)
            self._move_processed_to_archived(
                backup, accounts_with_processed, bucket_name, regional_client
            )
        except Exception as e:
            self.logger.exception(f"Failed to archive snapshot {backup.backup_id}: {e}")

    def _move_processed_to_archived(
        self,
        backup: BackupResource,
        accounts_with_processed: Dict[str, str],
        bucket_name: str,
        regional_client,
    ):
        engine_type = self.get_engine_type()
        for dest_account, processed_key in accounts_with_processed.items():
            archived_key = (
                f"{S3_DATA_PREFIX}/shared/{dest_account}/{engine_type}-archived/{backup.name}.yaml"
            )
            body = regional_client.get_object(Bucket=bucket_name, Key=processed_key)['Body'].read()
            regional_client.put_object(Bucket=bucket_name, Key=archived_key, Body=body)
            regional_client.delete_object(Bucket=bucket_name, Key=processed_key)
            self.logger.info(f"Moved shared backup info to s3://{bucket_name}/{archived_key}")

    def _get_s3_regional_client(self, bucket_name: str):
        s3_client = AwsHelper.boto3_client('s3')
        bucket_loc = s3_client.get_bucket_location(Bucket=bucket_name)
        bucket_region = bucket_loc['LocationConstraint']
        if bucket_region == 'EU':
            bucket_region = 'eu-west-1'
        elif bucket_region is None:
            bucket_region = 'us-east-1'
        return AwsHelper.boto3_client('s3', region_name=bucket_region)

    def _list_s3_objects(self, regional_client, bucket_name: str, prefix: str) -> List[dict]:
        all_objects = []
        response = regional_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
        if 'Contents' in response:
            all_objects.extend(response['Contents'])
        while 'NextContinuationToken' in response:
            response = regional_client.list_objects_v2(
                Bucket=bucket_name,
                Prefix=prefix,
                ContinuationToken=response['NextContinuationToken'],
            )
            if 'Contents' in response:
                all_objects.extend(response['Contents'])
        return all_objects

    def _s3_object_exists(self, regional_client, bucket_name: str, key: str) -> bool:
        try:
            regional_client.head_object(Bucket=bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise

    def _backup_name_from_s3_key(self, key: str) -> str:
        return key.split('/')[-1].replace('.yaml', '')

    def _load_backup_from_s3(self, regional_client, bucket_name: str, key: str) -> BackupResource:
        serialised = regional_client.get_object(Bucket=bucket_name, Key=key)['Body'].read()
        return yaml.load(serialised, Loader=yaml.Loader)

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
    
    def create_encrypted_backup(self, backup_id: str, kms_key: str, region: str) -> str:
        return backup_id
    
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
