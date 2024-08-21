import boto3

from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.engine import ShelveryEngine, SHELVERY_DO_BACKUP_TAGS
from shelvery.entity_resource import EntityResource

from typing import Dict, List
from botocore.errorfactory import ClientError
from shelvery.aws_helper import AwsHelper


class ShelveryDocumentDbBackup(ShelveryEngine):
    def is_backup_available(self, backup_region: str, backup_id: str) -> bool:
        docdb_client = AwsHelper.boto3_client('docdb', region_name=backup_region, arn=self.role_arn,
                                              external_id=self.role_external_id)
        snapshots = docdb_client.describe_db_cluster_snapshots(DBClusterSnapshotIdentifier=backup_id)
        return snapshots['DBClusterSnapshots'][0]['Status'] == 'available'

    def get_resource_type(self) -> str:
        return 'DocumentDb'

    def backup_resource(self, backup_resource: BackupResource) -> BackupResource:
        if RuntimeConfig.get_docdb_mode(backup_resource.entity_resource.tags,
                                        self) == RuntimeConfig.DOCDB_CREATE_SNAPSHOT:
            return self.backup_from_cluster(backup_resource)
        if RuntimeConfig.get_docdb_mode(backup_resource.entity_resource.tags,
                                        self) == RuntimeConfig.DOCDB_COPY_AUTOMATED_SNAPSHOT:
            return self.backup_from_latest_automated(backup_resource)

        raise Exception(f"Only {RuntimeConfig.DOCDB_COPY_AUTOMATED_SNAPSHOT} and "
                        f"{RuntimeConfig.DOCDB_CREATE_SNAPSHOT} documentdb backup "
                        f"modes supported - set documentdb backup mode using docdb_backup_mode configuration option ")

    def backup_from_latest_automated(self, backup_resource: BackupResource):
        docdb_client = AwsHelper.boto3_client('docdb', arn=self.role_arn, external_id=self.role_external_id)
        auto_snapshots = docdb_client.describe_db_cluster_snapshots(
            DBClusterIdentifier=backup_resource.entity_id,
            SnapshotType='automated',
            # API always returns in date descending order, and we only need last one
            MaxRecords=20
        )
        auto_snapshots = sorted(auto_snapshots['DBClusterSnapshots'], key=lambda k: k['SnapshotCreateTime'],
                                reverse=True)

        if len(auto_snapshots) == 0:
            self.logger.info(f"There is no latest automated backup for cluster {backup_resource.entity_id},"
                             f" fallback to DOCDB_CREATE_SNAPSHOT mode. Creating snapshot directly on cluster...")
            return self.backup_from_cluster(backup_resource)

        # TODO handle case when there are no latest automated backups
        automated_snapshot_id = auto_snapshots[0]['DBClusterSnapshotIdentifier']
        response = docdb_client.copy_db_cluster_snapshot(
            SourceDBClusterSnapshotIdentifier=automated_snapshot_id,
            TargetDBClusterSnapshotIdentifier=backup_resource.name,
            CopyTags=False
        )
        backup_resource.resource_properties = response['DBClusterSnapshot']
        backup_resource.backup_id = backup_resource.name
        return backup_resource

    def backup_from_cluster(self, backup_resource):
        docdb_client = AwsHelper.boto3_client('docdb', arn=self.role_arn, external_id=self.role_external_id)
        response = docdb_client.create_db_cluster_snapshot(
            DBClusterSnapshotIdentifier=backup_resource.name,
            DBClusterIdentifier=backup_resource.entity_id
        )
        backup_resource.resource_properties = response['DBClusterSnapshot']
        backup_resource.backup_id = backup_resource.name
        return backup_resource

    def delete_backup(self, backup_resource: BackupResource):
        docdb_client = AwsHelper.boto3_client('docdb', arn=self.role_arn, external_id=self.role_external_id)
        docdb_client.delete_db_cluster_snapshot(
            DBClusterSnapshotIdentifier=backup_resource.backup_id
        )

    def tag_backup_resource(self, backup_resource: BackupResource):
        regional_docdb_client = AwsHelper.boto3_client('docdb', region_name=backup_resource.region, arn=self.role_arn,
                                                       external_id=self.role_external_id)
        snapshots = regional_docdb_client.describe_db_cluster_snapshots(
            DBClusterSnapshotIdentifier=backup_resource.backup_id)
        snapshot_arn = snapshots['DBClusterSnapshots'][0]['DBClusterSnapshotArn']
        tags = list(map(lambda k: {'Key': k, 'Value': backup_resource.tags[k].replace(',', ' ')}, backup_resource.tags))
        regional_docdb_client.add_tags_to_resource(
            ResourceName=snapshot_arn,
            Tags=tags
        )

    def get_existing_backups(self, backup_tag_prefix: str) -> List[BackupResource]:
        docdb_client = AwsHelper.boto3_client('docdb', arn=self.role_arn, external_id=self.role_external_id)

        # collect all snapshots
        all_snapshots = self.collect_all_snapshots(docdb_client)

        # filter ones backed up with shelvery
        all_backups = self.get_shelvery_backups_only(all_snapshots, backup_tag_prefix, docdb_client)

        return all_backups

    def share_backup_with_account(self, backup_region: str, backup_id: str, aws_account_id: str):
        docdb_client = AwsHelper.boto3_client('docdb', region_name=backup_region, arn=self.role_arn,
                                              external_id=self.role_external_id)
        docdb_client.modify_db_cluster_snapshot_attribute(
            DBClusterSnapshotIdentifier=backup_id,
            AttributeName='restore',
            ValuesToAdd=[aws_account_id]
        )

    def copy_backup_to_region(self, backup_id: str, region: str) -> str:
        local_region = boto3.session.Session().region_name
        client_local = AwsHelper.boto3_client('docdb', arn=self.role_arn, external_id=self.role_external_id)
        docdb_client = AwsHelper.boto3_client('docdb', region_name=region)
        snapshots = client_local.describe_db_cluster_snapshots(DBClusterSnapshotIdentifier=backup_id)
        snapshot = snapshots['DBClusterSnapshots'][0]
        docdb_client.copy_db_cluster_snapshot(
            SourceDBClusterSnapshotIdentifier=snapshot['DBClusterSnapshotArn'],
            TargetDBClusterSnapshotIdentifier=backup_id,
            SourceRegion=local_region,
            # tags are created explicitly
            CopyTags=False
        )
        return backup_id
    
    def create_encrypted_backup(self, backup_id: str, kms_key: str, region: str) -> str:
        return backup_id

    def copy_shared_backup(self, source_account: str, source_backup: BackupResource):
        docdb_client = AwsHelper.boto3_client('docdb', arn=self.role_arn, external_id=self.role_external_id)
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
                self.logger.info(
                    f"Snapshot {source_backup.backup_id} will be copied and encrypted with the kms key {copy_kms_key}")
                kms_key = copy_kms_key

            params['KmsKeyId'] = kms_key
        else:
            # if the backup is not encrypted and the encrypt_copy is enabled, encrypted the backup with the provided kms key
            if RuntimeConfig.get_encrypt_copy(source_backup.tags, self):
                kms_key = RuntimeConfig.get_copy_kms_key_id(source_backup.tags, self)
                if kms_key is not None:
                    self.logger.info(
                        f"Snapshot {source_backup.backup_id} is not encrypted. Encrypting the copy with KMS key {kms_key}")
                    params['KmsKeyId'] = kms_key

        snap = docdb_client.copy_db_cluster_snapshot(**params)
        return snap['DBClusterSnapshot']['DBClusterSnapshotIdentifier']

    def get_backup_resource(self, backup_region: str, backup_id: str) -> BackupResource:
        docdb_client = AwsHelper.boto3_client('docdb', region_name=backup_region, arn=self.role_arn,
                                              external_id=self.role_external_id)
        snapshots = docdb_client.describe_db_cluster_snapshots(DBClusterSnapshotIdentifier=backup_id)
        snapshot = snapshots['DBClusterSnapshots'][0]
        tags = docdb_client.list_tags_for_resource(ResourceName=snapshot['DBClusterSnapshotArn']).get('TagList', [])
        d_tags = dict(map(lambda t: (t['Key'], t['Value']), tags))
        resource = BackupResource.construct(d_tags['shelvery:tag_name'], backup_id, d_tags)
        resource.resource_properties = snapshot
        return resource

    def get_engine_type(self) -> str:
        return 'docdb'

    def get_entities_to_backup(self, tag_name: str) -> List[EntityResource]:
        # region and api client
        local_region = boto3.session.Session().region_name
        docdb_client = AwsHelper.boto3_client('docdb', arn=self.role_arn, external_id=self.role_external_id)

        # list of models returned from api
        db_cluster_entities = []

        db_clusters = self.get_all_clusters(docdb_client)

        # collect tags in check if instance tagged with marker tag

        for instance in db_clusters:
            tags = docdb_client.list_tags_for_resource(ResourceName=instance['DBClusterArn']).get('TagList', [])

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

    def get_all_clusters(self, docdb_client):
        """
        Get all DocumentDb clusters within region for given boto3 client
        :param docdb_client: boto3 DocumentDb service
        :return: all DocumentDb instances within region for given boto3 client
        """
        # list of resource models
        db_clusters = []
        # temporary list of api models, as calls are batched
        temp_clusters = docdb_client.describe_db_clusters(
            Filters=[
                {
                    'Name': 'engine',
                    'Values': ['docdb',
                               ]
                },
            ])
        db_clusters.extend(temp_clusters['DBClusters'])
        # collect database instances
        while 'Marker' in temp_clusters:
            temp_clusters = docdb_client.describe_db_clusters(Marker=temp_clusters['Marker'])
            db_clusters.extend(temp_clusters['DBClusters'])

        return db_clusters

    def get_shelvery_backups_only(self, all_snapshots, backup_tag_prefix, docdb_client):
        """
        :param all_snapshots: all snapshots within region
        :param backup_tag_prefix:  prefix of shelvery backup system
        :param docdb_client:  amazon boto3 DocumentDb client
        :return: snapshots created using shelvery
        """
        all_backups = []
        marker_tag = f"{backup_tag_prefix}:{BackupResource.BACKUP_MARKER_TAG}"
        for snap in all_snapshots:
            tags = docdb_client.list_tags_for_resource(ResourceName=snap['DBClusterSnapshotArn']).get('TagList', [])
            self.logger.info(f"Checking DocumentDb Snapshot {snap['DBClusterSnapshotIdentifier']}")
            d_tags = dict(map(lambda t: (t['Key'], t['Value']), tags))
            if marker_tag in d_tags:
                if d_tags[marker_tag] in SHELVERY_DO_BACKUP_TAGS:
                    backup_resource = BackupResource.construct(backup_tag_prefix, snap['DBClusterSnapshotIdentifier'],
                                                               d_tags)
                    backup_resource.entity_resource = snap['EntityResource']
                    backup_resource.entity_id = snap['EntityResource'].resource_id

                    all_backups.append(backup_resource)

        return all_backups

    def collect_all_snapshots(self, docdb_client):
        """
        :param docdb_client:
        :return: All snapshots within region for docdb_client
        """
        all_snapshots = []

        self.logger.info("Collecting DB cluster snapshots...")
        tmp_snapshots = docdb_client.describe_db_cluster_snapshots(SnapshotType='manual')
        all_snapshots.extend(tmp_snapshots['DBClusterSnapshots'])

        while 'Marker' in tmp_snapshots:
            self.logger.info(
                f"Collected {len(tmp_snapshots['DBClusterSnapshots'])} manual snapshots. Continuing collection...")
            tmp_snapshots = docdb_client.describe_db_cluster_snapshots(SnapshotType='manual',
                                                                       Marker=tmp_snapshots['Marker'])
            all_snapshots.extend(tmp_snapshots['DBClusterSnapshots'])

        self.logger.info(f"Collected {len(all_snapshots)} manual snapshots.")
        self.populate_snap_entity_resource(all_snapshots)

        return all_snapshots

    def populate_snap_entity_resource(self, all_snapshots):
        cluster_ids = []

        for snap in all_snapshots:
            if snap['DBClusterIdentifier'] not in cluster_ids:
                cluster_ids.append(snap['DBClusterIdentifier'])

        entities = {}
        docdb_client = AwsHelper.boto3_client('docdb', arn=self.role_arn, external_id=self.role_external_id)
        local_region = boto3.session.Session().region_name

        for cluster_id in cluster_ids:
            try:
                self.logger.info(f"Collecting tags from DB cluster {cluster_id} ...")
                docdb_instance = docdb_client.describe_db_clusters(DBClusterIdentifier=cluster_id)['DBClusters'][0]
                tags = docdb_client.list_tags_for_resource(ResourceName=docdb_instance['DBClusterArn']).get('TagList', [])
                d_tags = dict(map(lambda t: (t['Key'], t['Value']), tags))
                docdb_entity = EntityResource(cluster_id,
                                              local_region,
                                              docdb_instance['ClusterCreateTime'],
                                              d_tags)
                entities[cluster_id] = docdb_entity
            except ClientError as e:
                if 'DBClusterNotFoundFault' in str(type(e)):
                    entities[cluster_id] = EntityResource.empty()
                    entities[cluster_id].resource_id = cluster_id
                else:
                    raise e

        for snap in all_snapshots:
            if snap['DBClusterIdentifier'] in entities:
                snap['EntityResource'] = entities[snap['DBClusterIdentifier']]
