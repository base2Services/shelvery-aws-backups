import unittest
import sys
import os
from unittest.mock import patch, MagicMock, call
from botocore.exceptions import ClientError

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


def head_object_not_found(*args, **kwargs):
    raise ClientError({'Error': {'Code': '404'}}, 'HeadObject')


class ShelveryEBSArchiveUnitTest(unittest.TestCase):
    """Unit tests for EBS Snapshots Archive tier feature"""

    def _make_engine(self):
        engine = ShelveryEBSBackup.__new__(ShelveryEBSBackup)
        engine.role_arn = None
        engine.role_external_id = None
        engine.logger = MagicMock()
        engine.lambda_payload = None
        engine.account_id = '111111111111'
        engine.region = 'ap-southeast-2'
        return engine

    def _make_backup_resource(self, retention_type, snapshot_id='snap-12345', tags=None):
        br = MagicMock(spec=BackupResource)
        br.backup_id = snapshot_id
        br.retention_type = retention_type
        br.region = 'ap-southeast-2'
        br.name = f'test-backup-{retention_type}'
        br.entity_resource = MagicMock(spec=EntityResource)
        br.entity_resource.tags = tags or {}
        br.tags = {
            'shelvery:tag_name': 'shelvery',
            'shelvery:retention_type': retention_type,
            'shelvery:name': br.name,
        }
        br.entity_resource_tags = MagicMock(return_value=tags or {})
        return br

    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_get_enable_ebs_archive_true(self):
        engine = MagicMock()
        engine.lambda_payload = None
        self.assertTrue(RuntimeConfig.get_enable_ebs_archive(None, engine))

    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'false'}, clear=False)
    def test_get_enable_ebs_archive_false(self):
        engine = MagicMock()
        engine.lambda_payload = None
        self.assertFalse(RuntimeConfig.get_enable_ebs_archive(None, engine))

    @patch.dict(os.environ, {}, clear=False)
    def test_get_enable_ebs_archive_default(self):
        os.environ.pop('shelvery_enable_ebs_archive', None)
        engine = MagicMock()
        engine.lambda_payload = None
        self.assertFalse(RuntimeConfig.get_enable_ebs_archive(None, engine))

    @patch.dict(os.environ, {'shelvery_enable_ebs_archive_pulled': 'true'}, clear=False)
    def test_get_enable_ebs_archive_pulled_true(self):
        engine = MagicMock()
        engine.lambda_payload = None
        self.assertTrue(RuntimeConfig.get_enable_ebs_archive_pulled(None, engine))

    def test_get_enable_ebs_archive_from_resource_tags(self):
        engine = MagicMock()
        engine.lambda_payload = None
        tags = {'shelvery:config:shelvery_enable_ebs_archive': 'true'}
        self.assertTrue(RuntimeConfig.get_enable_ebs_archive(tags, engine))

    @patch('shelvery.ebs_backup.AwsHelper')
    def test_archive_backup_calls_modify_snapshot_tier(self, mock_aws_helper):
        mock_client = MagicMock()
        mock_aws_helper.boto3_client.return_value = mock_client
        engine = self._make_engine()
        br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY, 'snap-abc123')

        engine.archive_backup(br)

        mock_client.modify_snapshot_tier.assert_called_once_with(
            SnapshotId='snap-abc123',
            StorageTier='archive'
        )

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive_pulled': 'true'}, clear=False)
    def test_post_pull_backups_archives_monthly(self, mock_aws_helper):
        mock_client = MagicMock()
        mock_aws_helper.boto3_client.return_value = mock_client
        engine = self._make_engine()
        engine.wait_backup_available = MagicMock(return_value=True)
        monthly_br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY, 'snap-monthly')

        engine.post_pull_backups([monthly_br])

        engine.wait_backup_available.assert_called_once_with('ap-southeast-2', 'snap-monthly', None, None)
        mock_client.modify_snapshot_tier.assert_called_once_with(
            SnapshotId='snap-monthly',
            StorageTier='archive'
        )

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive_pulled': 'true'}, clear=False)
    def test_post_pull_backups_skips_daily(self, mock_aws_helper):
        mock_client = MagicMock()
        mock_aws_helper.boto3_client.return_value = mock_client
        engine = self._make_engine()
        engine.wait_backup_available = MagicMock(return_value=True)
        daily_br = self._make_backup_resource(BackupResource.RETENTION_DAILY, 'snap-daily')

        engine.post_pull_backups([daily_br])

        engine.wait_backup_available.assert_not_called()
        mock_client.modify_snapshot_tier.assert_not_called()

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive_pulled': 'false'}, clear=False)
    def test_post_pull_backups_disabled_skips_monthly(self, mock_aws_helper):
        mock_client = MagicMock()
        mock_aws_helper.boto3_client.return_value = mock_client
        engine = self._make_engine()
        engine.wait_backup_available = MagicMock(return_value=True)
        monthly_br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY, 'snap-monthly')

        engine.post_pull_backups([monthly_br])

        engine.wait_backup_available.assert_not_called()
        mock_client.modify_snapshot_tier.assert_not_called()

    @patch('shelvery.ebs_backup.RuntimeConfig.get_share_with_accounts', return_value=[])
    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_archive_pending_backups_standalone_archives_monthly(
        self, mock_aws_helper, mock_share_accounts
    ):
        mock_client = MagicMock()
        mock_client.describe_snapshots.return_value = {
            'Snapshots': [{'StorageTier': 'standard', 'State': 'completed', 'Progress': '100%'}]
        }
        mock_aws_helper.boto3_client.return_value = mock_client
        engine = self._make_engine()
        engine.wait_backup_available = MagicMock(return_value=True)
        monthly_br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY, 'snap-monthly')

        with patch.object(ShelveryEBSBackup, 'get_existing_backups', return_value=[monthly_br]):
            engine.archive_pending_backups()

        mock_client.modify_snapshot_tier.assert_called_once_with(
            SnapshotId='snap-monthly',
            StorageTier='archive'
        )

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'false'}, clear=False)
    def test_archive_pending_backups_disabled_skips(self, mock_aws_helper):
        engine = self._make_engine()
        engine.get_existing_backups = MagicMock()
        engine.archive_backup = MagicMock()

        engine.archive_pending_backups()

        engine.get_existing_backups.assert_not_called()
        engine.archive_backup.assert_not_called()

    @patch('shelvery.ebs_backup.RuntimeConfig.get_share_with_accounts')
    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_archive_pending_backups_waits_for_all_share_targets(
        self, mock_aws_helper, mock_share_accounts
    ):
        mock_ec2 = MagicMock()
        mock_s3 = MagicMock()
        mock_aws_helper.boto3_client.side_effect = lambda service, **kwargs: mock_s3 if service == 's3' else mock_ec2

        engine = self._make_engine()
        mock_share_accounts.return_value = ['222222222222', '333333333333']

        def list_side_effect(Bucket, Prefix, ContinuationToken=None):
            if '222222222222/ebs-processed/' in Prefix:
                return {'Contents': [{'Key': 'backups/shared/222222222222/ebs-processed/test.yaml'}]}
            if '333333333333/ebs-processed/' in Prefix:
                return {'Contents': []}
            return {}

        mock_s3.get_bucket_location.return_value = {'LocationConstraint': 'ap-southeast-2'}
        mock_s3.list_objects_v2.side_effect = list_side_effect
        mock_s3.head_object.side_effect = head_object_not_found

        bucket = MagicMock()
        bucket.name = 'shelvery.data.111111111111-ap-southeast-2.base2tools'

        with patch.object(ShelveryEBSBackup, '_get_data_bucket', return_value=bucket):
            engine.archive_pending_backups()

        mock_ec2.modify_snapshot_tier.assert_not_called()

    @patch('shelvery.ebs_backup.RuntimeConfig.get_share_with_accounts')
    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_archive_pending_backups_archives_when_all_targets_processed(
        self, mock_aws_helper, mock_share_accounts
    ):
        mock_ec2 = MagicMock()
        mock_ec2.describe_snapshots.return_value = {
            'Snapshots': [{'StorageTier': 'standard', 'State': 'completed', 'Progress': '100%'}]
        }
        mock_s3 = MagicMock()
        mock_aws_helper.boto3_client.side_effect = lambda service, **kwargs: mock_s3 if service == 's3' else mock_ec2

        engine = self._make_engine()
        engine.wait_backup_available = MagicMock(return_value=True)
        monthly_br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY, 'snap-monthly')
        mock_share_accounts.return_value = ['222222222222', '333333333333']

        processed_key_a = 'backups/shared/222222222222/ebs-processed/test-backup-monthly.yaml'
        processed_key_b = 'backups/shared/333333333333/ebs-processed/test-backup-monthly.yaml'

        def list_side_effect(Bucket, Prefix, ContinuationToken=None):
            if '222222222222/ebs-processed/' in Prefix:
                return {'Contents': [{'Key': processed_key_a}]}
            if '333333333333/ebs-processed/' in Prefix:
                return {'Contents': [{'Key': processed_key_b}]}
            return {}

        mock_s3.get_bucket_location.return_value = {'LocationConstraint': 'ap-southeast-2'}
        mock_s3.list_objects_v2.side_effect = list_side_effect
        mock_s3.head_object.side_effect = head_object_not_found
        mock_s3.get_object.return_value = {
            'Body': MagicMock(read=MagicMock(return_value=b'backup-yaml'))
        }

        bucket = MagicMock()
        bucket.name = 'shelvery.data.111111111111-ap-southeast-2.base2tools'

        with patch.object(ShelveryEBSBackup, '_get_data_bucket', return_value=bucket):
            with patch.object(ShelveryEBSBackup, '_load_backup_from_s3', return_value=monthly_br):
                engine.archive_pending_backups()

        mock_ec2.modify_snapshot_tier.assert_called_once_with(
            SnapshotId='snap-monthly',
            StorageTier='archive'
        )
        mock_s3.delete_object.assert_has_calls([
            call(Bucket=bucket.name, Key=processed_key_a),
            call(Bucket=bucket.name, Key=processed_key_b),
        ], any_order=True)

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive_pulled': 'true'}, clear=False)
    def test_post_pull_backups_handles_api_error_gracefully(self, mock_aws_helper):
        mock_client = MagicMock()
        mock_client.modify_snapshot_tier.side_effect = Exception("API Error")
        mock_aws_helper.boto3_client.return_value = mock_client
        engine = self._make_engine()
        engine.wait_backup_available = MagicMock(return_value=True)
        monthly_br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY, 'snap-fail')

        engine.post_pull_backups([monthly_br])

        engine.logger.exception.assert_called_once()

    @patch('shelvery.ebs_backup.AwsHelper')
    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_should_archive_source_respects_resource_tag_override(self, mock_aws_helper):
        engine = self._make_engine()
        monthly_br = self._make_backup_resource(
            BackupResource.RETENTION_MONTHLY,
            tags={'shelvery:config:shelvery_enable_ebs_archive': 'false'},
        )

        self.assertFalse(engine._should_archive_source(monthly_br))

    @patch.dict(os.environ, {'shelvery_enable_ebs_archive': 'true'}, clear=False)
    def test_monthly_backups_remain_shareable_when_archive_enabled(self):
        """Monthly/yearly backups must still be shared so databunker can pull before archive."""
        engine = self._make_engine()
        monthly_br = self._make_backup_resource(BackupResource.RETENTION_MONTHLY)

        self.assertTrue(engine.is_backup_shareable(monthly_br))


if __name__ == '__main__':
    unittest.main()
