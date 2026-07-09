import sys
import unittest
import os
import pytest
from shelvery_tests.ebs_integration_test import EBSTestClass
from shelvery_tests.test_functions import (
    setup_destination,
    group_snapshots_by_retention_type,
    assert_snapshot_is_standard,
    assert_snapshot_is_archived_or_archiving,
)
from shelvery_tests.resources import EBS_INSTANCE_RESOURCE_NAME
from shelvery.backup_resource import BackupResource


pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

class ShelveryEBSPullTestCase(unittest.TestCase):

    def tearDown(self):
        os.environ.pop('shelvery_enable_ebs_archive_pulled', None)

    @pytest.mark.destination
    def test_PullEBSBackupWithArchivePulledEnabled(self):
        """Pull daily + monthly shared backups; only monthly is archived when enabled."""
        print("EBS - Running pull with archive_pulled enabled (daily + monthly)")
        setup_destination(self)
        os.environ['shelvery_enable_ebs_archive_pulled'] = 'true'

        ebs_test_class = EBSTestClass()
        backups_engine = ebs_test_class.backups_engine
        client = ebs_test_class.client

        backups_engine.clean_backups()

        search_filter = [{'Name': 'tag:ResourceName', 'Values': [EBS_INSTANCE_RESOURCE_NAME]}]
        pre_pull_snapshots = client.describe_snapshots(Filters=search_filter)['Snapshots']
        pre_pull_ids = {snapshot['SnapshotId'] for snapshot in pre_pull_snapshots}

        backups_engine.pull_shared_backups()

        post_pull_snapshots = client.describe_snapshots(Filters=search_filter)['Snapshots']
        pulled_snapshots = [
            snapshot for snapshot in post_pull_snapshots
            if snapshot['SnapshotId'] not in pre_pull_ids
        ]
        self.assertEqual(
            len(pulled_snapshots), 2,
            f"Expected exactly 2 new snapshots from pull (daily + monthly), got {len(pulled_snapshots)}"
        )

        by_retention = group_snapshots_by_retention_type(pulled_snapshots)
        self.assertIn(BackupResource.RETENTION_DAILY, by_retention)
        self.assertIn(BackupResource.RETENTION_MONTHLY, by_retention)

        for snapshot in pulled_snapshots:
            backups_engine.wait_backup_available(
                backups_engine.region,
                snapshot['SnapshotId'],
                None,
                None,
            )

        daily_snapshot = by_retention[BackupResource.RETENTION_DAILY][0]
        monthly_snapshot = by_retention[BackupResource.RETENTION_MONTHLY][0]

        assert_snapshot_is_standard(self, client, daily_snapshot['SnapshotId'])
        assert_snapshot_is_archived_or_archiving(self, client, monthly_snapshot['SnapshotId'])

    @pytest.mark.cleanup
    def test_cleanup(self):
        # Create test resource class
        ebs_test_class = EBSTestClass()
        backups_engine = ebs_test_class.backups_engine
         # Clean backups
        backups_engine.clean_backups()
