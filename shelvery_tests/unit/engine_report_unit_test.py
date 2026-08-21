import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

import shelvery.engine
from shelvery.entity_resource import EntityResource
from shelvery.factory import ShelveryFactory

# actions that must always produce a status report
REPORTED_ACTIONS = [
    'create_backups',
    'clean_backups',
    'pull_shared_backups',
    'create_data_buckets',
    'do_copy_backup',
    'do_share_backup',
    'do_store_backup_data',
]


def aws_patchers():
    """Stub every AWS call the engine makes while constructing and while running.

    BackupResource.__init__ also calls local_account_id, so these have to stay active for
    the whole test, not just while the engine is being built.
    """
    return [
        patch('shelvery.aws_helper.AwsHelper.local_account_id', return_value='123456789012'),
        patch('shelvery.aws_helper.AwsHelper.local_region', return_value='ap-southeast-2'),
        patch('shelvery.aws_helper.AwsHelper.boto3_client', return_value=MagicMock()),
    ]


class EngineTestCase(unittest.TestCase):

    def setUp(self):
        for p in aws_patchers():
            p.start()
            self.addCleanup(p.stop)

        self.engine = ShelveryFactory.get_shelvery_instance('ebs')
        self.engine.snspublisher = MagicMock()
        self.engine.snspublisher_error = MagicMock()

        # capture what publish_run_report sends, without reaching SNS
        self.published = []
        real = shelvery.engine.ShelveryNotification
        outer = self

        class CapturingNotification:
            def __init__(self, topic_arn):
                self.topic_arn = topic_arn

            def notify(self, message, subject=None):
                outer.published.append(message)

        shelvery.engine.ShelveryNotification = CapturingNotification
        self.addCleanup(setattr, shelvery.engine, 'ShelveryNotification', real)

    @property
    def report(self):
        return self.published[0]


class ReportIsAdditiveTest(EngineTestCase):
    """report() must never touch SNS - the per-operation notifications are unchanged."""

    def test_report_publishes_nothing(self):
        self.engine.start_run_report('create_backups')
        self.engine.report('CreateBackup', 'OK', entity_id='vol-1', backup_id='snap-1')

        self.engine.snspublisher.notify.assert_not_called()
        self.engine.snspublisher_error.notify.assert_not_called()

    def test_report_outside_a_run_is_a_no_op(self):
        self.engine.report('CreateBackup', 'OK', entity_id='vol-1')   # must not raise

    def test_entry_carries_the_resource_and_the_backup(self):
        self.engine.start_run_report('create_backups')
        self.engine.report('CreateBackup', 'OK', entity_id='vol-1', backup_id='snap-1',
                           backup_name='disk-daily')
        self.engine.publish_run_report()

        self.assertEqual({'operation': 'CreateBackup', 'status': 'OK', 'entity_id': 'vol-1',
                          'backup_id': 'snap-1', 'backup_name': 'disk-daily'},
                         self.report['entries'][0])

    def test_error_is_rendered_with_the_aws_error_code(self):
        self.engine.start_run_report('create_backups')
        self.engine.report('CreateBackup', 'ERROR', entity_id='db-1', error=ClientError(
            {'Error': {'Code': 'InvalidDBInstanceState', 'Message': 'busy'}}, 'CreateDBSnapshot'))
        self.engine.publish_run_report()

        self.assertTrue(self.report['entries'][0]['error'].startswith('InvalidDBInstanceState'))

    def test_publish_never_raises_when_sns_is_down(self):
        class Exploding:
            def __init__(self, arn):
                pass

            def notify(self, message, subject=None):
                raise RuntimeError('sns down')

        shelvery.engine.ShelveryNotification = Exploding
        self.engine.start_run_report('create_backups')
        self.engine.publish_run_report()   # must not raise


class DecoratorCoverageTest(EngineTestCase):
    """Guards against a future subclass override silently dropping reporting."""

    def test_every_engine_reports_every_action(self):
        for engine_type in ['ebs', 'ec2ami', 'rds', 'rds_cluster', 'redshift', 'docdb']:
            engine = ShelveryFactory.get_shelvery_instance(engine_type)
            for action in REPORTED_ACTIONS:
                method = getattr(type(engine), action)
                self.assertTrue(
                    getattr(method, '_shelvery_reported', False),
                    f"{type(engine).__name__}.{action} is missing @reported_action"
                )


class CreateBackupsReportTest(EngineTestCase):
    """The behaviour the status report exists to make visible."""

    def setUp(self):
        super().setUp()
        self.engine.tag_backup_resource = MagicMock()
        self.engine.store_backup_data = MagicMock()

    def stub_entities(self, count):
        self.engine.get_entities_to_backup = MagicMock(return_value=[
            EntityResource(f"vol-{i}", 'ap-southeast-2', '2026-08-14', {'Name': f"disk{i}"})
            for i in range(count)
        ])

    def test_no_resources_collected(self):
        self.stub_entities(0)
        self.engine.backup_resource = MagicMock()

        self.engine.create_backups()

        self.assertEqual('OK', self.report['status'])
        self.assertEqual(0, self.report['summary']['collected'])

    def test_all_succeeded(self):
        self.stub_entities(3)
        self.engine.backup_resource = MagicMock()

        self.engine.create_backups()

        self.assertEqual('OK', self.report['status'])
        self.assertEqual(3, self.report['summary']['succeeded'])
        self.assertEqual(3, self.report['summary']['collected'])

    def test_the_original_notifications_still_go_out(self):
        self.stub_entities(2)
        self.engine.backup_resource = MagicMock()

        self.engine.create_backups()

        self.assertEqual(2, self.engine.snspublisher.notify.call_count)
        self.assertEqual({
            'Operation': 'CreateBackup',
            'Status': 'OK',
            'BackupType': 'ebs',
            'BackupName': self.engine.snspublisher.notify.call_args[0][0]['BackupName'],
            'EntityId': 'vol-1',
        }, self.engine.snspublisher.notify.call_args[0][0])

    def test_a_non_client_error_does_not_abort_the_remaining_resources(self):
        # regression test: create_backups used to catch only ClientError, so a bare
        # Exception - such as the unsupported backup mode raised by the rds engines -
        # killed the loop and left every later resource silently un-backed-up
        self.stub_entities(3)
        attempts = []

        def backup_resource(br):
            attempts.append(br.entity_id)
            if len(attempts) == 2:
                raise RuntimeError('unsupported backup mode')
            br.backup_id = f"snap-{len(attempts)}"

        self.engine.backup_resource = backup_resource

        self.engine.create_backups()

        self.assertEqual(3, len(attempts), 'the third resource was never attempted')
        self.assertEqual('PARTIAL', self.report['status'])
        self.assertEqual(2, self.report['summary']['succeeded'])
        self.assertEqual(1, self.report['summary']['failed'])

    def test_failure_entry_carries_the_error(self):
        self.stub_entities(1)
        self.engine.backup_resource = MagicMock(
            side_effect=ClientError({'Error': {'Code': 'SnapshotLimitExceeded',
                                               'Message': 'too many'}}, 'CreateSnapshot'))

        self.engine.create_backups()

        failed = [e for e in self.report['entries'] if e['status'] == 'ERROR']
        self.assertEqual(1, len(failed))
        self.assertEqual('vol-0', failed[0]['entity_id'])
        self.assertTrue(failed[0]['error'].startswith('SnapshotLimitExceeded'))

    @patch.dict('os.environ', {'shelvery_keep_daily_backups': '0',
                               'shelvery_keep_weekly_backups': '0',
                               'shelvery_keep_monthly_backups': '0',
                               'shelvery_keep_yearly_backups': '0'})
    def test_retention_disabled_is_recorded_as_skipped_without_notifying(self):
        self.stub_entities(2)
        self.engine.backup_resource = MagicMock()

        self.engine.create_backups()

        self.engine.backup_resource.assert_not_called()
        self.assertEqual(2, self.report['summary']['skipped'])
        self.assertEqual('OK', self.report['status'])
        # this path has never emitted a notification and still doesn't
        self.engine.snspublisher.notify.assert_not_called()

    def test_an_unexpected_failure_aborts_the_run_but_still_reports(self):
        self.engine.get_entities_to_backup = MagicMock(
            side_effect=RuntimeError('describe_volumes blew up'))

        with self.assertRaises(RuntimeError):
            self.engine.create_backups()

        # the exception must still propagate so the Lambda Errors alarm fires, but the
        # report has to go out first
        self.assertEqual('FAILED', self.report['status'])
        self.assertIn('describe_volumes blew up', self.report['entries'][0]['error'])

    def test_report_identifies_the_run(self):
        self.stub_entities(1)
        self.engine.backup_resource = MagicMock()

        self.engine.create_backups()

        self.assertEqual('ebs', self.report['backup_type'])
        self.assertEqual('create_backups', self.report['action'])
        self.assertEqual('123456789012', self.report['account_id'])
        self.assertEqual('ap-southeast-2', self.report['region'])
        self.assertIsNotNone(self.report['run_id'])


if __name__ == '__main__':
    unittest.main()


class StoreBackupDataReportTest(EngineTestCase):
    """do_store_backup_data has no notification of its own, so its report line is easy to lose."""

    def test_a_successful_store_is_recorded(self):
        backup = MagicMock()
        backup.region = 'ap-southeast-2'
        backup.name = 'disk-2026-08-14-0100-daily'
        backup.account_id = '123456789012'

        self.engine.get_backup_resource = MagicMock(return_value=backup)
        self.engine.is_backup_available = MagicMock(return_value=True)
        self.engine._get_data_bucket = MagicMock()
        self.engine._write_backup_data = MagicMock()

        self.engine.do_store_backup_data(
            {'BackupId': 'snap-1', 'BackupRegion': 'ap-southeast-2'})

        entries = self.report['entries']
        self.assertEqual(1, len(entries), 'the report was empty - the report() line is missing')
        self.assertEqual('StoreBackupData', entries[0]['operation'])
        self.assertEqual('snap-1', entries[0]['backup_id'])
        self.assertEqual(1, self.report['summary']['succeeded'])
        # still report only - this path has never notified
        self.engine.snspublisher.notify.assert_not_called()


class NotApplicableActionTest(EngineTestCase):
    """An action that never enumerates should say nothing, not report an empty run."""

    def test_pull_shared_backups_publishes_nothing_when_no_source_accounts(self):
        with patch.dict('os.environ', {'shelvery_source_aws_account_ids': ''}):
            self.engine.pull_shared_backups()

        self.assertEqual([], self.published,
                         'a non-databunker account should not publish a pull report')

    def test_pull_shared_backups_still_reports_when_configured(self):
        self.engine.get_remote_bucket_name = MagicMock(return_value='some-bucket')

        with patch.dict('os.environ', {'shelvery_source_aws_account_ids': '111111111111'}):
            self.engine.pull_shared_backups()

        self.assertEqual(1, len(self.published))
        self.assertEqual('pull_shared_backups', self.published[0]['action'])


class ResourceContextTest(EngineTestCase):
    """A bare 'vol-046251e32bb3227c0' does not say which resource failed."""

    def setUp(self):
        super().setUp()
        self.engine.tag_backup_resource = MagicMock()
        self.engine.store_backup_data = MagicMock()
        self.engine.get_entities_to_backup = MagicMock(return_value=[
            EntityResource('vol-0abc', 'ap-southeast-2', '2026-08-17', {'Name': 'web-data'})
        ])

    def test_success_entry_names_the_resource_and_retention(self):
        def backup_resource(br):
            br.backup_id = 'snap-1'
        self.engine.backup_resource = backup_resource

        self.engine.create_backups()

        entry = self.report['entries'][0]
        self.assertEqual('vol-0abc', entry['entity_id'])
        self.assertEqual('web-data', entry['entity_name'])
        self.assertIn(entry['retention_type'], ['daily', 'weekly', 'monthly', 'yearly'])

    def test_failure_entry_names_the_resource_too(self):
        self.engine.backup_resource = MagicMock(
            side_effect=ClientError({'Error': {'Code': 'SnapshotLimitExceeded', 'Message': 'x'}},
                                    'CreateSnapshot'))

        self.engine.create_backups()

        failed = [e for e in self.report['entries'] if e['status'] == 'ERROR'][0]
        self.assertEqual('web-data', failed['entity_name'])
        self.assertEqual('vol-0abc', failed['entity_id'])

    def test_backup_context_reads_the_resource_name_tag_off_a_backup(self):
        from shelvery.backup_resource import BackupResource
        backup = BackupResource(None, None, True)
        backup.entity_id = 'vol-9'
        backup.retention_type = 'yearly'
        backup.tags = {'ResourceName': 'prod-db-volume'}

        self.assertEqual(
            {'entity_id': 'vol-9', 'entity_name': 'prod-db-volume', 'retention_type': 'yearly'},
            self.engine.backup_context(backup))

    def test_backup_context_tolerates_a_bare_object(self):
        self.assertEqual({'entity_id': None, 'entity_name': None, 'retention_type': None},
                         self.engine.backup_context(object()))
