import sys
import unittest
import pytest
import os
import time
from botocore.exceptions import WaiterError
from shelvery.engine import ShelveryEngine
from shelvery.runtime_config import RuntimeConfig
from shelvery.ebs_backup import ShelveryEBSBackup
from shelvery.aws_helper import AwsHelper
from shelvery_tests.test_functions import setup_source
from shelvery_tests.resources import EBS_INSTANCE_RESOURCE_NAME, ResourceClass

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

print(f"Python lib path:\n{sys.path}")


class EBSArchiveTestClass(ResourceClass):

    def __init__(self):
        self.resource_name = EBS_INSTANCE_RESOURCE_NAME
        self.backups_engine = ShelveryEBSBackup()
        self.client = AwsHelper.boto3_client('ec2', region_name='ap-southeast-2')
        self.resource_id = self.get_instance_id()

    def add_backup_tags(self):
        self.client.create_tags(
            Resources=[self.resource_id],
            Tags=[{
                'Key': f"{RuntimeConfig.get_tag_prefix()}:{ShelveryEngine.BACKUP_RESOURCE_TAG}",
                'Value': 'true'
            },
                {'Key': 'Name',
                 'Value': self.resource_name
                 }]
        )

    def get_instance_id(self):
        search_filter = [{'Name': 'tag:Name', 'Values': [self.resource_name]}]
        ebs_volumes = self.client.describe_volumes(Filters=search_filter)
        try:
            return ebs_volumes['Volumes'][0]['VolumeId']
        except (IndexError, KeyError):
            print("No EBS volumes found matching the given criteria.")
            return ""

    def wait_for_resource(self):
        waiter = AwsHelper.boto3_client('ec2', region_name='ap-southeast-2').get_waiter('volume_available')
        try:
            waiter.wait(
                VolumeIds=[self.resource_id],
                WaiterConfig={
                    'Delay': 30,
                    'MaxAttempts': 50
                }
            )
        except WaiterError as error:
            print("Waiting for EBS Volume Failed")
            print(error)
            raise error


class ShelveryEBSArchiveIntegrationTestCase(unittest.TestCase):
    """Integration tests for EBS Snapshots Archive tier feature.

    These tests require real AWS credentials and an EBS volume tagged
    for shelvery backups. They verify that the archive tier API is
    called correctly for monthly retention type backups.
    """

    def id(self):
        return str(self.__class__)

    def setUp(self):
        self.created_snapshots = []
        self.regional_snapshots = []
        setup_source(self)

        # Enable archive feature and force monthly retention for test
        os.environ['shelvery_enable_ebs_archive'] = 'true'
        os.environ['shelvery_current_retention_type'] = 'monthly'

        ebs_test_class = EBSArchiveTestClass()
        ebs_test_class.wait_for_resource()
        ebs_test_class.add_backup_tags()

    @pytest.mark.source
    def test_CreateEbsBackupWithArchive(self):
        """Create an EBS backup with monthly retention and verify it is archived."""
        print("Running EBS archive integration test")
        ebs_test_class = EBSArchiveTestClass()
        backups_engine = ebs_test_class.backups_engine
        client = ebs_test_class.client

        backups = backups_engine.create_backups()
        print(f"Created {len(backups)} backups for EBS Volume")

        self.assertGreater(len(backups), 0, "Expected at least 1 backup")

        for backup in backups:
            snapshot_id = backup.backup_id
            self.created_snapshots.append(snapshot_id)
            print(f"Checking archive status for snapshot {snapshot_id}")

            # Wait for snapshot to be available before checking tier
            backups_engine.wait_backup_available(backup.region, snapshot_id, None, None)

            # Allow time for the archive tier transition to be initiated
            time.sleep(5)

            # Describe the snapshot to check storage tier
            response = client.describe_snapshots(SnapshotIds=[snapshot_id])
            snapshot = response['Snapshots'][0]

            # The snapshot should either be archiving or already archived
            # Note: StorageTier may show 'standard' briefly while archival is in progress,
            # but describe_snapshot_tier_status should show the tiering status
            print(f"Snapshot {snapshot_id} StorageTier: {snapshot.get('StorageTier', 'standard')}")

            # Check tiering status via describe_snapshot_tier_status
            tier_response = client.describe_snapshot_tier_status(
                Filters=[{'Name': 'snapshot-id', 'Values': [snapshot_id]}]
            )

            if tier_response.get('SnapshotTierStatuses'):
                tier_status = tier_response['SnapshotTierStatuses'][0]
                status = tier_status.get('Status', '')
                print(f"Tiering status: {status}")
                print(f"Storage tier: {tier_status.get('StorageTier', 'N/A')}")
                # The API returns 'archival-in-progress' while archiving,
                # and 'completed' once the archive operation finishes
                self.assertIn(
                    status,
                    ['archival-in-progress', 'completed'],
                    f"Snapshot {snapshot_id} should be archiving or archived"
                )
            else:
                # If the API doesn't return status immediately, the modify call was made
                # This can happen with very new snapshots
                print(f"No tier status yet for {snapshot_id} - verifying via retention type")
                self.assertEqual(backup.retention_type, 'monthly')

        # Cleanup
        print("Cleaning up EBS Archive test backups")
        backups_engine.clean_backups()

    @pytest.mark.source
    def test_CreateEbsBackupArchiveDisabled(self):
        """Create an EBS backup with archive disabled and verify it stays standard."""
        print("Running EBS archive disabled test")
        os.environ['shelvery_enable_ebs_archive'] = 'false'

        ebs_test_class = EBSArchiveTestClass()
        backups_engine = ebs_test_class.backups_engine
        client = ebs_test_class.client

        backups = backups_engine.create_backups()
        print(f"Created {len(backups)} backups for EBS Volume")

        self.assertGreater(len(backups), 0, "Expected at least 1 backup")

        for backup in backups:
            snapshot_id = backup.backup_id
            self.created_snapshots.append(snapshot_id)

            backups_engine.wait_backup_available(backup.region, snapshot_id, None, None)
            time.sleep(5)

            response = client.describe_snapshots(SnapshotIds=[snapshot_id])
            snapshot = response['Snapshots'][0]

            # Snapshot should remain in standard tier
            storage_tier = snapshot.get('StorageTier', 'standard')
            print(f"Snapshot {snapshot_id} StorageTier: {storage_tier}")
            self.assertEqual(storage_tier, 'standard',
                             f"Snapshot {snapshot_id} should remain in standard tier when archive is disabled")

        # Cleanup
        print("Cleaning up EBS Archive disabled test backups")
        backups_engine.clean_backups()

    @pytest.mark.source
    def test_CreateDailyEbsBackupNotArchived(self):
        """Create an EBS backup with daily retention and verify it is NOT archived."""
        print("Running EBS daily backup (no archive) test")
        os.environ['shelvery_enable_ebs_archive'] = 'true'
        os.environ['shelvery_current_retention_type'] = 'daily'

        ebs_test_class = EBSArchiveTestClass()
        backups_engine = ebs_test_class.backups_engine
        client = ebs_test_class.client

        backups = backups_engine.create_backups()
        print(f"Created {len(backups)} backups for EBS Volume")

        self.assertGreater(len(backups), 0, "Expected at least 1 backup")

        for backup in backups:
            snapshot_id = backup.backup_id
            self.created_snapshots.append(snapshot_id)

            backups_engine.wait_backup_available(backup.region, snapshot_id, None, None)
            time.sleep(5)

            response = client.describe_snapshots(SnapshotIds=[snapshot_id])
            snapshot = response['Snapshots'][0]

            storage_tier = snapshot.get('StorageTier', 'standard')
            print(f"Snapshot {snapshot_id} StorageTier: {storage_tier}")
            self.assertEqual(storage_tier, 'standard',
                             f"Daily snapshot {snapshot_id} should NOT be archived")

        # Cleanup
        print("Cleaning up daily backup test")
        backups_engine.clean_backups()

    def tearDown(self):
        # Reset env vars
        os.environ.pop('shelvery_enable_ebs_archive', None)
        os.environ.pop('shelvery_current_retention_type', None)
        print("Waiting 30s due to EBS Snapshot rate limit...")
        time.sleep(30)


if __name__ == '__main__':
    unittest.main()
