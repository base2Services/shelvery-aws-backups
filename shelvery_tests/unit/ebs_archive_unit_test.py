import unittest
import sys
import os
from unittest.mock import patch, MagicMock
from datetime import datetime

pwd = os.path.dirname(os.path.abspath(__file__))
sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.ebs_backup import ShelveryEBSBackup
from shelvery.backup_resource import BackupResource
from shelvery.entity_resource import EntityResource
from shelvery.runtime_config import RuntimeConfig


class ShelveryEBSArchiveUnitTest(unittest.TestCase):
    """Unit tests for EBS Snapshots Archive tier feature"""

    def _make_backup_resource(self, retention_type, snapshot_id='snap-12345'):
        """Helper to create a mock BackupResource with given retention type."""
        br = MagicMock(spec=BackupResource)
        br.backup_id = snapshot_id
        br.retention_type = retention_type
        br.region = 'ap-southeast-2'
        br.entity_resource = MagicMock(spec=EntityResource)
        br.entity_resource.tags = {}
        return br

    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_get_enable_ebs_archive_true(self):
        """Config accessor returns True when env var is 'true'."""
        engine = MagicMock()
        engine.lambda_payload = None
        result = RuntimeConfig.get_enable_ebs_archive(None, engine)
        self.assertTrue(result)

    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'false'}, clear=False)
    def test_get_enable_ebs_archive_false(self):
        """Config accessor returns False when env var is 'false'."""
        engine = MagicMock()
        engine.lambda_payload = None
        result = RuntimeConfig.get_enable_ebs_archive(None, engine)
        self.assertFalse(result)

    @patch.dict(os.environ, {}, clear=False)
    def test_get_enable_ebs_archive_default(self):
        """Config accessor returns False when not set (uses default)."""
        os.environ.pop('shelvery_enable_ebs_archive', None)
        engine = MagicMock()
        engine.lambda_payload = None
        result = RuntimeConfig.get_enable_ebs_archive(None, engine)
        self.assertFalse(result)

    def test_get_enable_ebs_archive_from_resource_tags(self):
        """Config accessor reads from resource tags with highest priority."""
        engine = MagicMock()
        engine.lambda_payload = None
        tags = {'shelvery:config:shelvery_enable_ebs_archive': 'true'}
        result = RuntimeConfig.get_enable_ebs_archive(tags, engine)
        self.assertTrue(result)

    @patch('shelvery.ebs_backup.AwsHelper')
    def test_archive_backup_calls_modify_snapshot_tier(self, mock_aws_helper):
        """archive_backup calls ec2 modify_snapshot_tier with correct params."""
        mock_client = MagicMock()
        mock_aws_helper.boto3_client.return_value = mock_client

        engine = ShelveryEBSBackup.__new__(ShelveryEBSBackup)
        engine.role_arn = None
        engine.role_external_id = None
        engine.logger = MagicMock()

        br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY, 'snap-abc123')

        engine.archive_backup(br)

        mock_client.modify_snapshot_tier.assert_called_once_with(
            SnapshotId='snap-abc123',
            StorageTier='archive'
        )

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_post_create_backups_archives_monthly(self, mock_aws_helper):
        """post_create_backups archives monthly backups when feature enabled."""
        mock_client = MagicMock()
        mock_aws_helper.boto3_client.return_value = mock_client

        engine = ShelveryEBSBackup.__new__(ShelveryEBSBackup)
        engine.role_arn = None
        engine.role_external_id = None
        engine.logger = MagicMock()
        engine.lambda_payload = None
        engine.wait_backup_available = MagicMock(return_value=True)

        monthly_br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY, 'snap-monthly')

        engine.post_create_backups([monthly_br])

        engine.wait_backup_available.assert_called_once_with('ap-southeast-2', 'snap-monthly', None, None)
        mock_client.modify_snapshot_tier.assert_called_once_with(
            SnapshotId='snap-monthly',
            StorageTier='archive'
        )

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_post_create_backups_archives_yearly(self, mock_aws_helper):
        """post_create_backups archives yearly backups when feature enabled."""
        mock_client = MagicMock()
        mock_aws_helper.boto3_client.return_value = mock_client

        engine = ShelveryEBSBackup.__new__(ShelveryEBSBackup)
        engine.role_arn = None
        engine.role_external_id = None
        engine.logger = MagicMock()
        engine.lambda_payload = None
        engine.wait_backup_available = MagicMock(return_value=True)

        yearly_br = self._make_backup_resource(BackupResource.RETENTION_YEARLY, 'snap-yearly')

        engine.post_create_backups([yearly_br])

        engine.wait_backup_available.assert_called_once_with('ap-southeast-2', 'snap-yearly', None, None)
        mock_client.modify_snapshot_tier.assert_called_once_with(
            SnapshotId='snap-yearly',
            StorageTier='archive'
        )

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_post_create_backups_skips_daily(self, mock_aws_helper):
        """post_create_backups does NOT archive daily backups."""
        mock_client = MagicMock()
        mock_aws_helper.boto3_client.return_value = mock_client

        engine = ShelveryEBSBackup.__new__(ShelveryEBSBackup)
        engine.role_arn = None
        engine.role_external_id = None
        engine.logger = MagicMock()
        engine.lambda_payload = None
        engine.wait_backup_available = MagicMock(return_value=True)

        daily_br = self._make_backup_resource(BackupResource.RETENTION_DAILY, 'snap-daily')

        engine.post_create_backups([daily_br])

        engine.wait_backup_available.assert_not_called()
        mock_client.modify_snapshot_tier.assert_not_called()

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_post_create_backups_skips_weekly(self, mock_aws_helper):
        """post_create_backups does NOT archive weekly backups."""
        mock_client = MagicMock()
        mock_aws_helper.boto3_client.return_value = mock_client

        engine = ShelveryEBSBackup.__new__(ShelveryEBSBackup)
        engine.role_arn = None
        engine.role_external_id = None
        engine.logger = MagicMock()
        engine.lambda_payload = None
        engine.wait_backup_available = MagicMock(return_value=True)

        weekly_br = self._make_backup_resource(BackupResource.RETENTION_WEEKLY, 'snap-weekly')

        engine.post_create_backups([weekly_br])

        engine.wait_backup_available.assert_not_called()
        mock_client.modify_snapshot_tier.assert_not_called()

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'false'}, clear=False)
    def test_post_create_backups_disabled_skips_monthly(self, mock_aws_helper):
        """post_create_backups does NOT archive when feature is disabled."""
        mock_client = MagicMock()
        mock_aws_helper.boto3_client.return_value = mock_client

        engine = ShelveryEBSBackup.__new__(ShelveryEBSBackup)
        engine.role_arn = None
        engine.role_external_id = None
        engine.logger = MagicMock()
        engine.lambda_payload = None
        engine.wait_backup_available = MagicMock(return_value=True)

        monthly_br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY, 'snap-monthly')

        engine.post_create_backups([monthly_br])

        engine.wait_backup_available.assert_not_called()
        mock_client.modify_snapshot_tier.assert_not_called()

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_post_create_backups_mixed_retention_types(self, mock_aws_helper):
        """post_create_backups only archives monthly/yearly from a mixed list."""
        mock_client = MagicMock()
        mock_aws_helper.boto3_client.return_value = mock_client

        engine = ShelveryEBSBackup.__new__(ShelveryEBSBackup)
        engine.role_arn = None
        engine.role_external_id = None
        engine.logger = MagicMock()
        engine.lambda_payload = None
        engine.wait_backup_available = MagicMock(return_value=True)

        daily_br = self._make_backup_resource(BackupResource.RETENTION_DAILY, 'snap-daily')
        weekly_br = self._make_backup_resource(BackupResource.RETENTION_WEEKLY, 'snap-weekly')
        monthly_br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY, 'snap-monthly')
        yearly_br = self._make_backup_resource(BackupResource.RETENTION_YEARLY, 'snap-yearly')

        engine.post_create_backups([daily_br, weekly_br, monthly_br, yearly_br])

        self.assertEqual(engine.wait_backup_available.call_count, 2)
        calls = mock_client.modify_snapshot_tier.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs['SnapshotId'], 'snap-monthly')
        self.assertEqual(calls[1].kwargs['SnapshotId'], 'snap-yearly')

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_post_create_backups_handles_api_error_gracefully(self, mock_aws_helper):
        """post_create_backups logs but does not raise on archive failure."""
        mock_client = MagicMock()
        mock_client.modify_snapshot_tier.side_effect = Exception("API Error")
        mock_aws_helper.boto3_client.return_value = mock_client

        engine = ShelveryEBSBackup.__new__(ShelveryEBSBackup)
        engine.role_arn = None
        engine.role_external_id = None
        engine.logger = MagicMock()
        engine.lambda_payload = None
        engine.wait_backup_available = MagicMock(return_value=True)

        monthly_br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY, 'snap-fail')

        # Should not raise
        engine.post_create_backups([monthly_br])

        engine.logger.exception.assert_called_once()

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_post_create_backups_per_resource_tag_override(self, mock_aws_helper):
        """Archive is skipped for a resource that has the tag set to false."""
        mock_client = MagicMock()
        mock_aws_helper.boto3_client.return_value = mock_client

        engine = ShelveryEBSBackup.__new__(ShelveryEBSBackup)
        engine.role_arn = None
        engine.role_external_id = None
        engine.logger = MagicMock()
        engine.lambda_payload = None
        engine.wait_backup_available = MagicMock(return_value=True)

        monthly_br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY, 'snap-override')
        monthly_br.entity_resource.tags = {
            'shelvery:config:shelvery_enable_ebs_archive': 'false'
        }

        engine.post_create_backups([monthly_br])

        engine.wait_backup_available.assert_not_called()
        mock_client.modify_snapshot_tier.assert_not_called()


if __name__ == '__main__':
    unittest.main()
