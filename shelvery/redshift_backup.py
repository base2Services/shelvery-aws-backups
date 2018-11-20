import boto3, datetime
from botocore.exceptions import ClientError

from typing import List

from shelvery.engine import SHELVERY_DO_BACKUP_TAGS
from shelvery.engine import ShelveryEngine

from shelvery.entity_resource import EntityResource
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.aws_helper import AwsHelper

class ShelveryRedshiftBackup(ShelveryEngine):
	def __init__(self):
		ShelveryEngine.__init__(self)
		self.redshift_client = AwsHelper.boto3_client('redshift', arn=self.role_arn, external_id=self.role_external_id)
		# default region will be picked up in AwsHelper.boto3_client call
		self.region = boto3.session.Session().region_name

	def get_resource_type(self) -> str:
		"""Returns entity type that's about to be backed up"""
		return 'Redshift Cluster'

	def get_engine_type(self) -> str:
		"""
		Return engine type, valid string to be passed to ShelveryFactory.get_shelvery_instance method
		"""
		return 'redshift'

	def delete_backup(self, backup_resource: BackupResource):
		"""
		Remove given backup from system
		"""
		redshift_client = AwsHelper.boto3_client('redshift', region_name = backup_resource.region, arn=self.role_arn, external_id=self.role_external_id)
		cluster_id = backup_resource.backup_id.split(":")[-1].split("/")[0]
		snapshot_id = backup_resource.backup_id.split(":")[-1].split("/")[1]
		try:
			redshift_client.delete_cluster_snapshot(
				SnapshotIdentifier=snapshot_id,
				SnapshotClusterIdentifier=cluster_id
			)
		except ClientError as ex:
			if 'other accounts still have access to it' in ex.response['Error']['Message']:
				self.logger.exception(f"Could not delete {backup_resource.backup_id} as"
				f"other accounts still have access to this snapshot")
				return
			else:
				self.logger.error(ex.response)
				self.logger.exception(f"Could not delete {backup_resource.backup_id}")

	def get_existing_backups(self, backup_tag_prefix: str) -> List[BackupResource]:
		"""
		Collect existing backups on system of given type, marked with given tag
		"""
		local_region = boto3.session.Session().region_name
		marker_tag = f"{backup_tag_prefix}:{BackupResource.BACKUP_MARKER_TAG}"
		response = self.redshift_client.describe_cluster_snapshots(
            SnapshotType='manual',
            TagKeys=[marker_tag],
            TagValues=SHELVERY_DO_BACKUP_TAGS
        )

		snapshots = response['Snapshots']
		backups = []

		for snap in snapshots:
			cluster_id = snap['ClusterIdentifier']
			d_tags = BackupResource.dict_from_boto3_tags(snap['Tags'])
			create_time = snap['ClusterCreateTime']
			redshift_entity = EntityResource(cluster_id,
											local_region,
											create_time,
											d_tags)
			backup_id = f"arn:aws:redshift:{local_region}:{snap['OwnerAccount']}"
			backup_id = f"{backup_id}:snapshot:{snap['ClusterIdentifier']}/{snap['SnapshotIdentifier']}"
			backup_resource = BackupResource.construct(
                backup_tag_prefix,
				backup_id,
                d_tags
            )
			backup_resource.entity_resource = redshift_entity
			backup_resource.entity_id = redshift_entity.resource_id

			backups.append(backup_resource)

		return backups

	def get_entities_to_backup(self, tag_name: str) -> List[EntityResource]:
		"""Get all instances that contain `tag_name` as a tag."""
		clusters = self.collect_clusters(tag_name)

		# TODO: To get the cluster's creation time, we need to query the "events" with the
		# cluster ID.

		entities = []
		for cluster in clusters:
			if cluster['ClusterStatus'] != 'available':
				self.logger.info(f"Skipping cluster '{cluster['ClusterIdentifier']}' as its status is '{cluster['ClusterStatus']}'.")
				continue

			d_tags = BackupResource.dict_from_boto3_tags(cluster['Tags'])

			entity = EntityResource(
				resource_id=cluster['ClusterIdentifier'],
				resource_region=self.region,
				date_created=f"{datetime.datetime.utcnow():%Y-%m-%d %H:%M:%S}",
				tags=d_tags)
			entities.append(entity)

		return entities

	# collect all clusters tagged with given tag, in paginated manner
	def collect_clusters(self, tag_name: str):
		load_clusters = True
		next_token = ''
		all_clusters = []

		while load_clusters:
			tagged_clusters = self.redshift_client.describe_clusters(TagKeys=[tag_name], TagValues=SHELVERY_DO_BACKUP_TAGS)
			all_clusters = all_clusters + tagged_clusters['Clusters']
			if 'Marker' in tagged_clusters and len(tagged_clusters['Marker']) > 0:
				load_clusters = True
				next_token = tagged_clusters['Marker']
			else:
				load_clusters = False

		return all_clusters

	def backup_resource(self, backup_resource: BackupResource) -> BackupResource:
		"""Redshift supports two modes of snapshot functions: a regular cluster snapshot and copying an existing snapshot to a different region.
		"""
		if RuntimeConfig.get_redshift_mode(backup_resource.entity_resource.tags, self) == RuntimeConfig.REDSHIFT_CREATE_SNAPSHOT:
			return self.backup_from_cluster(backup_resource)
		if RuntimeConfig.get_redshift_mode(backup_resource.entity_resource.tags,
									  self) == RuntimeConfig.REDSHIFT_COPY_AUTOMATED_SNAPSHOT:
			return self.backup_from_latest_automated(backup_resource)

		raise Exception(f"Only {RuntimeConfig.REDSHIFT_COPY_AUTOMATED_SNAPSHOT} and "
						f"{RuntimeConfig.REDSHIFT_CREATE_SNAPSHOT} redshift backup "
						f"modes supported - set redshift backup mode using redshift_backup_mode configuration option ")

	def backup_from_cluster(self, backup_resource: BackupResource):
		snapshot = self.redshift_client.create_cluster_snapshot(
			SnapshotIdentifier=backup_resource.name,
			ClusterIdentifier=backup_resource.entity_id,
		)['Snapshot']
		backup_resource.backup_id = f"arn:aws:redshift:{backup_resource.region}:{backup_resource.account_id}"
		backup_resource.backup_id = f"{backup_resource.backup_id}:snapshot:{snapshot['ClusterIdentifier']}/{snapshot['SnapshotIdentifier']}"
		return backup_resource

	def backup_from_latest_automated(self, backup_resource: BackupResource):
		auto_snapshots = self.redshift_client.describe_cluster_snapshots(
			ClusterIdentifier=backup_resource.entity_id,
			SnapshotType='automated',
			# API always returns in date descending order, and we only need last one
			MaxRecords=20
		)
		auto_snapshots = sorted(auto_snapshots['Snapshots'], key=lambda k: k['SnapshotCreateTime'],
								reverse=True)

		if len(auto_snapshots) == 0:
			self.logger.error(f"There is no latest automated backup for cluster {backup_resource.entity_id},"
							  f" fallback to REDSHIFT_CREATE_SNAPSHOT mode. Creating snapshot directly on cluster...")
			return self.backup_from_cluster(backup_resource)

		# TODO handle case when there are no latest automated backups
		snapshot = self.redshift_client.copy_cluster_snapshot(
			SourceSnapshotIdentifier=auto_snapshots[0]['SnapshotIdentifier'],
			SourceSnapshotClusterIdentifier=auto_snapshots[0]['ClusterIdentifier'],
			TargetSnapshotIdentifier=backup_resource.name
		)['Snapshot']
		backup_resource.backup_id = f"arn:aws:redshift:{backup_resource.region}:{backup_resource.account_id}"
		backup_resource.backup_id = f"{backup_resource.backup_id}:snapshot:{snapshot['ClusterIdentifier']}/{snapshot['SnapshotIdentifier']}"
		return backup_resource

	def tag_backup_resource(self, backup_resource: BackupResource):
		"""
		Create backup resource tags.
		"""
		# This is unnecessary for Redshift as the tags are included when calling `backup_resource()`.
		redshift_client = AwsHelper.boto3_client('redshift', region_name = backup_resource.region, arn=self.role_arn, external_id=self.role_external_id)
		redshift_client.create_tags(
			ResourceName=backup_resource.backup_id,
			Tags=backup_resource.boto3_tags
		)

	def copy_backup_to_region(self, backup_id: str, region: str) -> str:
		"""
		Copy a backup to another region.
		This enables cross-region automated backups for the Redshift cluster, so future automated backups
		will be replicated to `region`.
		"""
		self.logger.warning("Redshift does not support copy of a snapshot as such to another region, "
							"but rather allows automatic copying of automated backups to another region"
							"using EnableSnapshotCopy API Call.")
		pass

	def is_backup_available(self, backup_region: str, backup_id: str) -> bool:
		"""
		Determine whether backup has completed and is available to be copied
		to other regions and shared with other AWS accounts
		"""
		redshift_client = AwsHelper.boto3_client('redshift', region_name=backup_region, arn=self.role_arn, external_id=self.role_external_id)
		snapshot_id = backup_id.split(":")[-1].split("/")[1]
		snapshots = None
		try:
			snapshots = redshift_client.describe_cluster_snapshots(
				SnapshotIdentifier=snapshot_id
			)
		except ClientError as e:
			self.logger.warning(f"Backup {backup_id} not found")
			print(e.response)
			if e.response['Error']['Code'] == '404':
				return False
			else:
				self.logger.exception(f"Problem waiting for {backup_id} availability")
				raise e
		return snapshots['Snapshots'][0]['Status'] == 'available'


	def share_backup_with_account(self, backup_region: str, backup_id: str, aws_account_id: str):
		"""
		Share backup with another AWS Account
		"""
		redshift_client = AwsHelper.boto3_client('redshift', region_name=backup_region, arn=self.role_arn, external_id=self.role_external_id)
		snapshot_id = backup_id.split(":")[-1].split("/")[1]
		redshift_client.authorize_snapshot_access(
			SnapshotIdentifier=snapshot_id,
			AccountWithRestoreAccess=aws_account_id
		)


	def get_backup_resource(self, backup_region: str, backup_id: str) -> BackupResource:
		"""
		Get Backup Resource within region, identified by its backup_id
		"""
		redshift_client = AwsHelper.boto3_client('redshift', region_name=backup_region, arn=self.role_arn, external_id=self.role_external_id)
		snapshot_id = backup_id.split(":")[-1].split("/")[1]
		snapshots = redshift_client.describe_cluster_snapshots(SnapshotIdentifier=snapshot_id)
		snapshot = snapshots['Snapshots'][0]
		d_tags = BackupResource.dict_from_boto3_tags(snapshot['Tags'])
		return BackupResource.construct(d_tags['shelvery:tag_name'], backup_id, d_tags)

	def copy_shared_backup(self, source_account: str, source_backup: BackupResource) -> str:
		"""
		Copy Shelvery backup that has been shared from another account to account where
		shelvery is currently running
		:param source_account:
		:param source_backup:
		:return:
		"""
		self.logger.warning("Redshift does not support cross account copy of snapshots as such. "
							"Alternate way of creating snapshot copy is creating cluster out of"
							"shared snapshot, and then creating snapshot out of that cluster.")
		return source_backup.backup_id
