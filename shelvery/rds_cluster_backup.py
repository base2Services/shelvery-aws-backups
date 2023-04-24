from tracemalloc import Snapshot
import boto3

from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.engine import ShelveryEngine, SHELVERY_DO_BACKUP_TAGS
from shelvery.entity_resource import EntityResource

from typing import Dict, List
from botocore.errorfactory import ClientError
from shelvery.aws_helper import AwsHelper

class ShelveryRDSClusterBackup(ShelveryEngine):
    def is_backup_available(self, backup_region: str, backup_id: str) -> bool:
        rds_client = AwsHelper.boto3_client('rds', region_name=backup_region, arn=self.role_arn, external_id=self.role_external_id)
        snapshots = rds_client.describe_db_cluster_snapshots(DBClusterSnapshotIdentifier=backup_id)
        return snapshots['DBClusterSnapshots'][0]['Status'] == 'available'

    def get_resource_type(self) -> str:
        return 'RDS Cluster'

    def backup_resource(self, backup_resource: BackupResource) -> BackupResource:
        if RuntimeConfig.get_rds_mode(backup_resource.entity_resource.tags, self) == RuntimeConfig.RDS_CREATE_SNAPSHOT:
            return self.backup_from_cluster(backup_resource)
        if RuntimeConfig.get_rds_mode(backup_resource.entity_resource.tags,
                                      self) == RuntimeConfig.RDS_COPY_AUTOMATED_SNAPSHOT:
            return self.backup_from_latest_automated(backup_resource)

        raise Exception(f"Only {RuntimeConfig.RDS_COPY_AUTOMATED_SNAPSHOT} and "
                        f"{RuntimeConfig.RDS_CREATE_SNAPSHOT} rds backup "
                        f"modes supported - set rds backup mode using rds_backup_mode configuration option ")

    def backup_from_latest_automated(self, backup_resource: BackupResource):
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)
        auto_snapshots = rds_client.describe_db_cluster_snapshots(
            DBClusterIdentifier=backup_resource.entity_id,
            SnapshotType='automated',
            # API always returns in date descending order, and we only need last one
            MaxRecords=20
        )
        auto_snapshots = sorted(auto_snapshots['DBClusterSnapshots'], key=lambda k: k['SnapshotCreateTime'],
                                reverse=True)

        if len(auto_snapshots) == 0:
            self.logger.info(f"There is no latest automated backup for cluster {backup_resource.entity_id},"
                              f" fallback to RDS_CREATE_SNAPSHOT mode. Creating snapshot directly on cluster...")
            return self.backup_from_cluster(backup_resource)

        # TODO handle case when there are no latest automated backups
        automated_snapshot_id = auto_snapshots[0]['DBClusterSnapshotIdentifier']
        response = rds_client.copy_db_cluster_snapshot(
            SourceDBClusterSnapshotIdentifier=automated_snapshot_id,
            TargetDBClusterSnapshotIdentifier=backup_resource.name,
            CopyTags=False
        )
        backup_resource.resource_properties = response['DBClusterSnapshot']
        backup_resource.backup_id = backup_resource.name
        return backup_resource

    def backup_from_cluster(self, backup_resource):
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)
        response = rds_client.create_db_cluster_snapshot(
            DBClusterSnapshotIdentifier=backup_resource.name,
            DBClusterIdentifier=backup_resource.entity_id
        )
        backup_resource.resource_properties = response['DBClusterSnapshot']
        backup_resource.backup_id = backup_resource.name
        return backup_resource

    def delete_backup(self, backup_resource: BackupResource):
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)
        rds_client.delete_db_cluster_snapshot(
            DBClusterSnapshotIdentifier=backup_resource.backup_id
        )

    def tag_backup_resource(self, backup_resource: BackupResource):
        regional_rds_client = AwsHelper.boto3_client('rds', region_name=backup_resource.region, arn=self.role_arn, external_id=self.role_external_id)
        snapshots = regional_rds_client.describe_db_cluster_snapshots(
            DBClusterSnapshotIdentifier=backup_resource.backup_id)
        snapshot_arn = snapshots['DBClusterSnapshots'][0]['DBClusterSnapshotArn']
        tags = list(map(lambda k: {'Key': k, 'Value': backup_resource.tags[k].replace(',', ' ')}, backup_resource.tags))
        regional_rds_client.add_tags_to_resource(
            ResourceName=snapshot_arn,
            Tags=tags
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
        backup_resource = self.get_backup_resource(backup_region, backup_id)
        kms_key = RuntimeConfig.get_reencrypt_kms_key_id(backup_resource.tags, self)
        
        # if a re-encrypt key is provided, create new re-encrypted snapshot and share that instead
        if kms_key:
            self.logger.info(f"Re-encrypt KMS Key found, creating new backup with {kms_key}")
            # create re-encrypted backup
            backup_id = self.copy_backup_to_region(backup_id, backup_region)
            self.logger.info(f"Creating new encrypted backup {backup_id}")
            # wait till new snapshot is available
            if not self.wait_backup_available(backup_region=backup_region,
                backup_id=backup_id,
                lambda_method='do_share_backup',
                lambda_args={}):
                return
            self.logger.info(f"New encrypted backup {backup_id} created")
            
            #Get new snapshot ARN 
            snapshots = rds_client.describe_db_cluster_snapshots(DBClusterSnapshotIdentifier=backup_id)
            snapshot_arn = snapshots['DBClusterSnapshots'][0]['DBClusterSnapshotArn']
           
            #Update tags with '-re-encrypted' suffix
            self.logger.info(f"Updating tags for new snapshot - {backup_id}")
            tags = self.get_backup_resource(backup_region, backup_id).tags
            tags.update({'Name': backup_id, 'shelvery:name': backup_id})
            tag_list = [{'Key': key, 'Value': value} for key, value in tags.items()]
            rds_client.add_tags_to_resource(
                ResourceName=snapshot_arn,
                Tags=tag_list
            )
            created_new_encrypted_snapshot = True
        else:
            self.logger.info(f"No re-encrypt key detected")
            created_new_encrypted_snapshot = False 
            
        rds_client.modify_db_cluster_snapshot_attribute(
            DBClusterSnapshotIdentifier=backup_id,
            AttributeName='restore',
            ValuesToAdd=[aws_account_id]
        )
        # if re-encryption occured, clean up old snapshot
        if created_new_encrypted_snapshot:
            # delete old snapshot
            self.delete_backup(backup_resource)
            self.logger.info(f"Cleaning up un-encrypted backup: {backup_resource.backup_id}")
        
        return backup_id

    def copy_backup_to_region(self, backup_id: str, region: str) -> str:
        local_region = boto3.session.Session().region_name
        client_local = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)
        rds_client = AwsHelper.boto3_client('rds', region_name=region)
        snapshots = client_local.describe_db_cluster_snapshots(DBClusterSnapshotIdentifier=backup_id)
        snapshot = snapshots['DBClusterSnapshots'][0]
        backup_resource = self.get_backup_resource(local_region, backup_id)
        kms_key = RuntimeConfig.get_reencrypt_kms_key_id(backup_resource.tags, self)
        rds_client_params = {
            'SourceDBClusterSnapshotIdentifier': snapshot['DBClusterSnapshotArn'],
            'TargetDBClusterSnapshotIdentifier': backup_id,
            'SourceRegion': local_region,
            'CopyTags': False
        }
        # add kms key params if re-encrypt key is defined
        if kms_key is not None:
            backup_id = f'{backup_id}-re-encrypted'
            rds_client_params['KmsKeyId'] = kms_key
            rds_client_params['CopyTags'] = True
            rds_client_params['TargetDBClusterSnapshotIdentifier'] = backup_id
                       
        rds_client.copy_db_cluster_snapshot(**rds_client_params)
        return backup_id

    def copy_shared_backup(self, source_account: str, source_backup: BackupResource):
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)
        # copying of tags happens outside this method
        source_arn = f"arn:aws:rds:{source_backup.region}:{source_backup.account_id}:cluster-snapshot:{source_backup.backup_id}"

        params = {
            'SourceDBClusterSnapshotIdentifier': source_arn,
            'SourceRegion': source_backup.region,
            'CopyTags': False,
            'TargetDBClusterSnapshotIdentifier': source_backup.backup_id
        }

        # If the backup is encrypted, include the KMS key ID in the request.
        if source_backup.resource_properties['StorageEncrypted']:
            kms_key = source_backup.resource_properties['KmsKeyId']
            self.logger.info(f"Snapshot {source_backup.backup_id} is encrypted with the kms key {kms_key}")
            
            copy_kms_key = RuntimeConfig.get_copy_kms_key_id(source_backup.tags, self)
            # if a new key is provided by config encypt the copy with the new kms key
            if copy_kms_key is not None:
                self.logger.info(f"Snapshot {source_backup.backup_id} will be copied and encrypted with the kms key {copy_kms_key}")
                kms_key = copy_kms_key
                
            params['KmsKeyId'] = kms_key
        else:
            # if the backup is not encrypted and the encrypt_copy is enabled, encrypted the backup with the provided kms key
            if RuntimeConfig.get_encrypt_copy(source_backup.tags, self):
                kms_key = RuntimeConfig.get_copy_kms_key_id(source_backup.tags, self)
                if kms_key is not None:
                    self.logger.info(f"Snapshot {source_backup.backup_id} is not encrypted. Encrypting the copy with KMS key {kms_key}")
                    params['KmsKeyId'] = kms_key
        
        snap = rds_client.copy_db_cluster_snapshot(**params)
        return snap['DBClusterSnapshot']['DBClusterSnapshotIdentifier']

    def get_backup_resource(self, backup_region: str, backup_id: str) -> BackupResource:
        rds_client = AwsHelper.boto3_client('rds', region_name=backup_region, arn=self.role_arn, external_id=self.role_external_id)
        snapshots = rds_client.describe_db_cluster_snapshots(DBClusterSnapshotIdentifier=backup_id)
        snapshot = snapshots['DBClusterSnapshots'][0]
        tags = snapshot['TagList']
        d_tags = dict(map(lambda t: (t['Key'], t['Value']), tags))
        resource = BackupResource.construct(d_tags['shelvery:tag_name'], backup_id, d_tags)
        resource.resource_properties = snapshot
        return resource

    def get_engine_type(self) -> str:
        return 'rds_cluster'

    def get_entities_to_backup(self, tag_name: str) -> List[EntityResource]:
        # region and api client
        local_region = boto3.session.Session().region_name
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)

        # list of models returned from api
        db_cluster_entities = []

        db_clusters = self.get_all_clusters(rds_client)

        # collect tags in check if instance tagged with marker tag

        for instance in db_clusters:
            tags = instance['TagList']

            # convert api response to dictionary
            d_tags = dict(map(lambda t: (t['Key'], t['Value']), tags))

            # check if marker tag is present
            if tag_name in d_tags and d_tags[tag_name] in SHELVERY_DO_BACKUP_TAGS:
                resource = EntityResource(instance['DBClusterIdentifier'],
                                          local_region,
                                          instance['ClusterCreateTime'],
                                          d_tags)
                db_cluster_entities.append(resource)

        return db_cluster_entities

    def get_all_clusters(self, rds_client):
        """
        Get all RDS clusters within region for given boto3 client
        :param rds_client: boto3 rds service
        :return: all RDS instances within region for given boto3 client
        """
        # list of resource models
        db_clusters = []
        # temporary list of api models, as calls are batched
        temp_clusters = rds_client.describe_db_clusters()
        
        db_clusters.extend(temp_clusters['DBClusters'])
        # collect database instances
        while 'Marker' in temp_clusters:
            temp_clusters = rds_client.describe_db_clusters(Marker=temp_clusters['Marker'])
            db_clusters.extend(temp_clusters['DBClusters'])

        db_clusters = [cluster for cluster in db_clusters if cluster.get('Engine') != 'docdb']
        return db_clusters

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
            tags = snap['TagList']
            self.logger.info(f"Checking RDS Snap {snap['DBClusterSnapshotIdentifier']}")
            d_tags = dict(map(lambda t: (t['Key'], t['Value']), tags))
            if marker_tag in d_tags:
                if d_tags[marker_tag] in SHELVERY_DO_BACKUP_TAGS:
                    backup_resource = BackupResource.construct(backup_tag_prefix, snap['DBClusterSnapshotIdentifier'],
                                                               d_tags)
                    backup_resource.entity_resource = snap['EntityResource']
                    backup_resource.entity_id = snap['EntityResource'].resource_id

                    all_backups.append(backup_resource)

        return all_backups

    def collect_all_snapshots(self, rds_client):
        """
        :param rds_client:
        :return: All snapshots within region for rds_client
        """
        all_snapshots = []

        self.logger.info("Collecting DB cluster snapshots...")
        tmp_snapshots = rds_client.describe_db_cluster_snapshots(SnapshotType='manual')
        all_snapshots.extend(tmp_snapshots['DBClusterSnapshots'])

        while 'Marker' in tmp_snapshots:
            self.logger.info(f"Collected {len(tmp_snapshots['DBClusterSnapshots'])} manual snapshots. Continuing collection...")
            tmp_snapshots = rds_client.describe_db_cluster_snapshots(SnapshotType='manual', Marker=tmp_snapshots['Marker'])
            all_snapshots.extend(tmp_snapshots['DBClusterSnapshots'])
            
        all_snapshots = [snapshot for snapshot in all_snapshots if snapshot.get('Engine') != 'docdb']

        self.logger.info(f"Collected {len(all_snapshots)} manual snapshots.")
        self.populate_snap_entity_resource(all_snapshots)

        return all_snapshots

    def populate_snap_entity_resource(self, all_snapshots):
        cluster_ids = []

        for snap in all_snapshots:
            if snap['DBClusterIdentifier'] not in cluster_ids:
                cluster_ids.append(snap['DBClusterIdentifier'])

        entities = {}
        rds_client = AwsHelper.boto3_client('rds', arn=self.role_arn, external_id=self.role_external_id)
        local_region = boto3.session.Session().region_name

        for cluster_id in cluster_ids:
            try:
                self.logger.info(f"Collecting tags from DB cluster {cluster_id} ...")
                rds_instance = rds_client.describe_db_clusters(DBClusterIdentifier=cluster_id)['DBClusters'][0]
                tags = rds_instance['TagList']
                d_tags = dict(map(lambda t: (t['Key'], t['Value']), tags))
                rds_entity = EntityResource(cluster_id,
                                            local_region,
                                            rds_instance['ClusterCreateTime'],
                                            d_tags)
                entities[cluster_id] = rds_entity
            except ClientError as e:
                if 'DBClusterNotFoundFault' in str(type(e)):
                    entities[cluster_id] = EntityResource.empty()
                    entities[cluster_id].resource_id = cluster_id
                else:
                    raise e

        for snap in all_snapshots:
            if snap['DBClusterIdentifier'] in entities:
                snap['EntityResource'] = entities[snap['DBClusterIdentifier']]
