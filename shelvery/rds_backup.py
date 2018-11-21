import boto3

from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.engine import ShelveryEngine, SHELVERY_DO_BACKUP_TAGS
from shelvery.entity_resource import EntityResource

from typing import Dict, List
from botocore.errorfactory import ClientError
from shelvery.aws_helper import AwsHelper

class ShelveryRDSBackup(ShelveryEngine):
    def is_backup_available(self, backup_region: str, backup_id: str) -> bool:
        rds_client = AwsHelper.boto3_client('rds', region_name=backup_region, arn=self.role_arn, external_id=self.role_external_id)
        snapshots = rds_client.describe_db_snapshots(DBSnapshotIdentifier=backup_id)
        return snapshots['DBSnapshots'][0]['Status'] == 'available'

    def get_resource_type(self) -> str:
        return 'RDS Instance'

    def backup_resource(self, backup_resource: BackupResource) -> BackupResource:
        if RuntimeConfig.get_rds_mode(backup_resource.entity_resource.tags, self) == RuntimeConfig.RDS_CREATE_SNAPSHOT:
            return self.backup_from_instance(backup_resource)
        if RuntimeConfig.get_rds_mode(backup_resource.entity_resource.tags,
                                      self) == RuntimeConfig.RDS_COPY_AUTOMATED_SNAPSHOT:
            return self.backup_from_latest_automated(backup_resource)

        raise Exception(f"Only {RuntimeConfig.RDS_COPY_AUTOMATED_SNAPSHOT} and "
                        f"{RuntimeConfig.RDS_CREATE_SNAPSHOT} rds backup "
                        f"modes supported - set rds backup mode using rds_backup_mode configuration option ")

    def backup_from_latest_automated(self, backup_resource: BackupResource):
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)
        auto_snapshots = rds_client.describe_db_snapshots(
            DBInstanceIdentifier=backup_resource.entity_id,
            SnapshotType='automated',
            # API always returns in date descending order, and we only need last one
            MaxRecords=20
        )
        auto_snapshots = sorted(auto_snapshots['DBSnapshots'], key=lambda k: k['SnapshotCreateTime'], reverse=True)

        if len(auto_snapshots) == 0:
            self.logger.info(f"There is no latest automated backup for cluster {backup_resource.entity_id},"
                              f" fallback to RDS_CREATE_SNAPSHOT mode. Creating snapshot directly on cluster...")
            return self.backup_from_instance(backup_resource)

        automated_snapshot_id = auto_snapshots[0]['DBSnapshotIdentifier']
        rds_client.copy_db_snapshot(
            SourceDBSnapshotIdentifier=automated_snapshot_id,
            TargetDBSnapshotIdentifier=backup_resource.name,
            CopyTags=False
        )
        backup_resource.backup_id = backup_resource.name
        return backup_resource

    def backup_from_instance(self, backup_resource):
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)
        rds_client.create_db_snapshot(
            DBSnapshotIdentifier=backup_resource.name,
            DBInstanceIdentifier=backup_resource.entity_id
        )
        backup_resource.backup_id = backup_resource.name
        return backup_resource

    def delete_backup(self, backup_resource: BackupResource):
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn)
        rds_client.delete_db_snapshot(
            DBSnapshotIdentifier=backup_resource.backup_id
        )

    def tag_backup_resource(self, backup_resource: BackupResource):
        regional_rds_client = AwsHelper.boto3_client('rds', region_name=backup_resource.region, arn=self.role_arn, external_id=self.role_external_id)
        snapshots = regional_rds_client.describe_db_snapshots(DBSnapshotIdentifier=backup_resource.backup_id)
        snapshot_arn = snapshots['DBSnapshots'][0]['DBSnapshotArn']
        regional_rds_client.add_tags_to_resource(
            ResourceName=snapshot_arn,
            Tags=list(
                map(lambda k: {'Key': k, 'Value': backup_resource.tags[k].replace(',', ' ')}, backup_resource.tags))
        )

    def get_existing_backups(self, backup_tag_prefix: str) -> List[BackupResource]:
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)

        # collect all snapshots
        all_snapshots = self.collect_all_snapshots(rds_client)

        # filter ones backed up with shelvery
        all_backups = self.get_shelvery_backups_only(all_snapshots, backup_tag_prefix, rds_client)

        return all_backups

    def share_backup_with_account(self, backup_region: str, backup_id: str, aws_account_id: str):
        rds_client = AwsHelper.boto3_client('rds', region_name=backup_region, arn=self.role_arn, external_id=self.role_external_id)
        rds_client.modify_db_snapshot_attribute(
            DBSnapshotIdentifier=backup_id,
            AttributeName='restore',
            ValuesToAdd=[aws_account_id]
        )

    def copy_backup_to_region(self, backup_id: str, region: str) -> str:
        local_region = boto3.session.Session().region_name
        client_local = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)
        rds_client = AwsHelper.boto3_client('rds', region_name=region, arn=self.role_arn, external_id=self.role_external_id)
        snapshots = client_local.describe_db_snapshots(DBSnapshotIdentifier=backup_id)
        snapshot = snapshots['DBSnapshots'][0]
        rds_client.copy_db_snapshot(
            SourceDBSnapshotIdentifier=snapshot['DBSnapshotArn'],
            TargetDBSnapshotIdentifier=backup_id,
            SourceRegion=local_region,
            # tags are created explicitly
            CopyTags=False
        )
        return backup_id

    def get_backup_resource(self, backup_region: str, backup_id: str) -> BackupResource:
        rds_client = AwsHelper.boto3_client('rds', region_name=backup_region, arn=self.role_arn, external_id=self.role_external_id)
        snapshots = rds_client.describe_db_snapshots(DBSnapshotIdentifier=backup_id)
        snapshot = snapshots['DBSnapshots'][0]
        tags = rds_client.list_tags_for_resource(ResourceName=snapshot['DBSnapshotArn'])['TagList']
        d_tags = dict(map(lambda t: (t['Key'], t['Value']), tags))
        return BackupResource.construct(d_tags['shelvery:tag_name'], backup_id, d_tags)

    def get_engine_type(self) -> str:
        return 'rds'

    def get_entities_to_backup(self, tag_name: str) -> List[EntityResource]:
        # region and api client
        local_region = boto3.session.Session().region_name
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)

        # list of models returned from api
        db_entities = []

        db_instances = self.get_all_instances(rds_client)

        # collect tags in check if instance tagged with marker tag

        for instance in db_instances:
            tags = rds_client.list_tags_for_resource(ResourceName=instance['DBInstanceArn'])['TagList']

            # convert api response to dictionary
            d_tags = dict(map(lambda t: (t['Key'], t['Value']), tags))

            if 'DBClusterIdentifier' in instance:
                self.logger.info(f"Skipping RDS Instance {instance['DBInstanceIdentifier']} as it is part"
                                 f" of cluster {instance['DBClusterIdentifier']}")
                continue

            # check if marker tag is present
            if tag_name in d_tags and d_tags[tag_name] in SHELVERY_DO_BACKUP_TAGS:
                resource = EntityResource(instance['DBInstanceIdentifier'],
                                          local_region,
                                          instance['InstanceCreateTime'],
                                          d_tags)
                db_entities.append(resource)

        return db_entities

    def get_all_instances(self, rds_client):
        """
        Get all RDS instances within region for given boto3 client
        :param rds_client: boto3 rds service
        :return: all RDS instances within region for given boto3 client
        """
        # list of resource models
        db_instances = []
        # temporary list of api models, as calls are batched
        temp_instances = rds_client.describe_db_instances()
        db_instances.extend(temp_instances['DBInstances'])
        # collect database instances
        while 'Marker' in temp_instances:
            temp_instances = rds_client.describe_db_instances(Marker=temp_instances['Marker'])
            db_instances.extend(temp_instances['DBInstances'])

        return db_instances

    def get_shelvery_backups_only(self, all_snapshots, backup_tag_prefix, rds_client):
        """
        :param all_snapshots: all snapshots within region
        :param backup_tag_prefix:  prefix of shelvery backup system
        :param rds_client:  amazon boto3 rds client
        :return: snapshots created using shelvery
        """
        all_backups = []
        marker_tag = f"{backup_tag_prefix}:{BackupResource.BACKUP_MARKER_TAG}"
        for snap in all_snapshots:
            tags = rds_client.list_tags_for_resource(ResourceName=snap['DBSnapshotArn'])['TagList']
            self.logger.info(f"Checking RDS Snap {snap['DBSnapshotIdentifier']}")
            d_tags = dict(map(lambda t: (t['Key'], t['Value']), tags))
            if marker_tag in d_tags:
                if d_tags[marker_tag] in SHELVERY_DO_BACKUP_TAGS:
                    backup_resource = BackupResource.construct(backup_tag_prefix, snap['DBSnapshotIdentifier'], d_tags)
                    backup_resource.entity_resource = snap['EntityResource']
                    backup_resource.entity_id = snap['EntityResource'].resource_id

                    all_backups.append(backup_resource)

        return all_backups

    def copy_shared_backup(self, source_account: str, source_backup: BackupResource):
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)
        # copying of tags happens outside this method
        source_arn = f"arn:aws:rds:{source_backup.region}:{source_backup.account_id}:snapshot:{source_backup.backup_id}"
        snap = rds_client.copy_db_snapshot(
            SourceDBSnapshotIdentifier=source_arn,
            SourceRegion=source_backup.region,
            CopyTags=False,
            TargetDBSnapshotIdentifier=source_backup.backup_id
        )
        return snap['DBSnapshot']['DBSnapshotIdentifier']

    def collect_all_snapshots(self, rds_client):
        """
        :param rds_client:
        :return: All snapshots within region for rds_client
        """
        all_snapshots = []
        tmp_snapshots = rds_client.describe_db_snapshots(SnapshotType='manual')
        all_snapshots.extend(tmp_snapshots['DBSnapshots'])
        while 'Marker' in tmp_snapshots:
            tmp_snapshots = rds_client.describe_db_snapshots(Marker=tmp_snapshots['Marker'])
            all_snapshots.extend(tmp_snapshots['DBSnapshots'])

        self.populate_snap_entity_resource(all_snapshots)

        return all_snapshots

    def populate_snap_entity_resource(self, all_snapshots):
        instance_ids = []
        for snap in all_snapshots:
            if snap['DBInstanceIdentifier'] not in instance_ids:
                instance_ids.append(snap['DBInstanceIdentifier'])
        entities = {}
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)
        local_region = boto3.session.Session().region_name

        for instance_id in instance_ids:
            try:
                rds_instance = rds_client.describe_db_instances(DBInstanceIdentifier=instance_id)['DBInstances'][0]
                tags = rds_client.list_tags_for_resource(ResourceName=rds_instance['DBInstanceArn'])['TagList']
                d_tags = dict(map(lambda t: (t['Key'], t['Value']), tags))
                rds_entity = EntityResource(instance_id,
                                            local_region,
                                            rds_instance['InstanceCreateTime'],
                                            d_tags)
                entities[instance_id] = rds_entity
            except ClientError as e:
                if 'DBInstanceNotFoundFault' in str(type(e)):
                    entities[instance_id] = EntityResource.empty()
                    entities[instance_id].resource_id = instance_id
                else:
                    raise e

        for snap in all_snapshots:
            if snap['DBInstanceIdentifier'] in entities:
                snap['EntityResource'] = entities[snap['DBInstanceIdentifier']]
