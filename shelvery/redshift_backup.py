import boto3, datetime

from typing import List

from shelvery.engine import SHELVERY_DO_BACKUP_TAGS
from shelvery.engine import ShelveryEngine

from shelvery.entity_resource import EntityResource
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource

class ShelveryRedshiftBackup(ShelveryEngine):
	def __init__(self):
		ShelveryEngine.__init__(self)
		self.redshift_client = boto3.client('redshift')
		# default region will be picked up in boto3.client call
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

	def get_existing_backups(self, backup_tag_prefix: str) -> List[BackupResource]:
		"""
		Collect existing backups on system of given type, marked with given tag
		"""

	def get_entities_to_backup(self, tag_name: str) -> List[EntityResource]:
		"""Get all instances that contain `tag_name` as a tag."""
		clusters = self.collect_clusters(tag_name)

		# TODO: To get the cluster's creation time, we need to query the "events" with the
		# cluster ID.

		entities = []
		for cluster in clusters:
			tags = cluster['Tags']
			d_tags = dict(map(lambda t: (t['Key'], t['Value']), tags))

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
		tags = list(map(lambda k: {'Key': k, 'Value': backup_resource.tags[k].replace(',', ' ')}, backup_resource.tags))

		self.redshift_client.create_cluster_snapshot(
			SnapshotIdentifier=backup_resource.name,
			ClusterIdentifier=backup_resource.entity_id,
			Tags=tags
		)
		backup_resource.backup_id = backup_resource.name
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
							  f" fallback to RDS_CREATE_SNAPSHOT mode. Creating snapshot directly on cluster...")
			return self.backup_from_cluster(backup_resource)

		# TODO handle case when there are no latest automated backups
		automated_snapshot_id = auto_snapshots[0]['SnapshotIdentifier']
		self.redshift_client.copy_cluster_snapshot(
			SourceSnapshotIdentifier=automated_snapshot_id,
			TargetSnapshotIdentifier=backup_resource.name,
			CopyTags=False 	# TODO: should this be true?
		)
		backup_resource.backup_id = backup_resource.name
		return backup_resource

	def tag_backup_resource(self, backup_resource: BackupResource):
		"""
		Create backup resource tags.
		"""
		# This is unnecessary as the tags are included in `backup_resource()`.
		pass

	def copy_backup_to_region(self, backup_id: str, region: str) -> str:
		"""
		Copy backup to another region
		"""

	def is_backup_available(self, backup_region: str, backup_id: str) -> bool:
		"""
		Determine whether backup has completed and is available to be copied
		to other regions and shared with other AWS accounts
		"""
		redshift_client = boto3.client('redshift', region_name=backup_region)
		snapshots = redshift_client.describe_db_cluster_snapshots(SnapshotIdentifier=backup_id)
		return snapshots['Snapshots'][0]['Status'] == 'available'


	def share_backup_with_account(self, backup_region: str, backup_id: str, aws_account_id: str):
		"""
		Share backup with another AWS Account
		"""

	def get_backup_resource(self, backup_region: str, backup_id: str) -> BackupResource:
		"""
		Get Backup Resource within region, identified by its backup_id
		"""



