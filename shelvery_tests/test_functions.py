import os
import boto3
import time
import yaml
from shelvery_tests.conftest import destination_account, source_account
from shelvery.runtime_config import RuntimeConfig
from shelvery.aws_helper import AwsHelper

def setup_source(self):
    print(f"Setting up integration test")
    self.share_with_id = destination_account
    os.environ["shelvery_share_aws_account_ids"] = destination_account
    os.environ['AWS_DEFAULT_REGION'] = 'ap-southeast-2'
    os.environ['SHELVERY_MONO_THREAD'] = '1'
    os.environ['shelvery_custom_retention_types'] = 'shortLived:1'
    os.environ['shelvery_current_retention_type'] = 'shortLived'
    
    sts = AwsHelper.boto3_client('sts')
    self.id = sts.get_caller_identity()
    print(f"Running as user:\n{self.id}\n")

def setup_destination(self):
    print(f"Setting up integration test")

    os.environ['AWS_DEFAULT_REGION'] = 'ap-southeast-2'
    os.environ['SHELVERY_MONO_THREAD'] = '1'
    os.environ['shelvery_custom_retention_types'] = 'shortLived:1'
    os.environ['shelvery_current_retention_type'] = 'shortLived'
    os.environ["shelvery_source_aws_account_ids"] = source_account
    
    sts = AwsHelper.boto3_client('sts')
    self.id = sts.get_caller_identity()
    print(f"Running as user:\n{self.id}\n")

def compare_backups(self,backup,backup_engine):
    print("Inside backup loop" + backup.backup_id)
    snapshot_id = backup.backup_id
    self.created_snapshots.append(snapshot_id)
    print("Snapshot:" + str(snapshot_id))

    # wait for snapshot to become available
    backup_engine.wait_backup_available(backup.region, backup.backup_id, None, None)

    # allow buffer period for engine to write data to s3
    time.sleep(20)

    # this is the backup that gets stored in s3
    engine_backup = backup_engine.get_backup_resource(backup.region, backup.backup_id)
    # verify the s3 data
    account_id = backup_engine.account_id
    s3path = f"backups/{backup_engine.get_engine_type()}/{engine_backup.name}.yaml"
    s3bucket = backup_engine.get_local_bucket_name()
    print(f"Using bucket {s3bucket}")
    print(f"Using path {s3path}")
    bucket = boto3.resource('s3').Bucket(s3bucket)
    object = bucket.Object(s3path)
    content = object.get()['Body'].read()
    restored_br = yaml.load(content, Loader=yaml.Loader)
    self.assertEqual(restored_br.backup_id, engine_backup.backup_id)
    self.assertEqual(restored_br.name, engine_backup.name)
    self.assertEqual(restored_br.region, engine_backup.region)
    print(f"Tags restored: \n{yaml.dump(restored_br.tags)}\n")
    print(f"Tags backup: \n{yaml.dump(engine_backup.tags)}\n")
    self.assertEqual(restored_br.tags['Name'], engine_backup.tags['Name'])
    for tag in ['name', 'date_created', 'entity_id', 'region', 'retention_type']:
        self.assertEqual(
            restored_br.tags[f"{RuntimeConfig.get_tag_prefix()}:{tag}"],
            engine_backup.tags[f"{RuntimeConfig.get_tag_prefix()}:{tag}"]
        )
    
    return True


def snapshot_retention_type(snapshot: dict) -> str:
    """Return shelvery retention_type from EC2 snapshot tags."""
    tag_prefix = RuntimeConfig.get_tag_prefix()
    tags = {tag['Key']: tag['Value'] for tag in snapshot.get('Tags', [])}
    return tags.get(f"{tag_prefix}:retention_type", '')


def group_snapshots_by_retention_type(snapshots: list) -> dict:
    """Group describe_snapshots results by shelvery retention_type tag."""
    grouped = {}
    for snapshot in snapshots:
        retention_type = snapshot_retention_type(snapshot)
        grouped.setdefault(retention_type, []).append(snapshot)
    return grouped


def assert_snapshot_is_standard(test_case, client, snapshot_id: str) -> None:
    """Assert an EBS snapshot remains on the standard storage tier."""
    response = client.describe_snapshots(SnapshotIds=[snapshot_id])
    storage_tier = response['Snapshots'][0].get('StorageTier', 'standard')
    test_case.assertEqual(
        storage_tier,
        'standard',
        f"Snapshot {snapshot_id} should remain standard tier, got {storage_tier}"
    )


def assert_snapshot_is_archived_or_archiving(test_case, client, snapshot_id: str) -> None:
    """Assert an EBS snapshot is archived or archival is in progress."""
    time.sleep(5)
    snapshot = client.describe_snapshots(SnapshotIds=[snapshot_id])['Snapshots'][0]
    storage_tier = snapshot.get('StorageTier', 'standard')
    if storage_tier == 'archive':
        return

    tier_response = client.describe_snapshot_tier_status(
        Filters=[{'Name': 'snapshot-id', 'Values': [snapshot_id]}]
    )
    if tier_response.get('SnapshotTierStatuses'):
        status = tier_response['SnapshotTierStatuses'][0].get('Status', '')
        test_case.assertIn(
            status,
            ['archival-in-progress', 'completed'],
            f"Snapshot {snapshot_id} should be archiving or archived, got status {status!r}"
        )
        return

    test_case.fail(
        f"Snapshot {snapshot_id} expected archive tier or tiering status, "
        f"got StorageTier={storage_tier!r}"
    )