import json
import unittest

from botocore.exceptions import ClientError

from shelvery.backup_report import ABORTED, MAX_ENTRIES, RunReport, describe_error


def make_report(*statuses):
    report = RunReport(action='create_backups', backup_type='ebs',
                       account_id='123456789012', region='ap-southeast-2')
    for status in statuses:
        report.add({'operation': 'CreateBackup', 'status': status})
    return report


class StatusTest(unittest.TestCase):
    """The pass/fail verdict is the point of the report, so pin every branch."""

    def test_no_entries_is_ok(self):
        self.assertEqual('OK', make_report().status)

    def test_all_succeeded_is_ok(self):
        self.assertEqual('OK', make_report('OK', 'OK').status)

    def test_skipped_only_is_ok(self):
        self.assertEqual('OK', make_report('IGNORE', 'IGNORE').status)

    def test_some_failed_is_partial(self):
        self.assertEqual('PARTIAL', make_report('OK', 'ERROR').status)

    def test_all_failed_is_failed(self):
        self.assertEqual('FAILED', make_report('ERROR', 'ERROR').status)

    def test_aborted_is_failed_even_with_successes(self):
        self.assertEqual('FAILED', make_report('OK', 'OK', ABORTED).status)


class SummaryTest(unittest.TestCase):

    def test_counters_match_entries(self):
        report = make_report('OK', 'OK', 'ERROR', 'IGNORE')
        report.collected = 4
        summary = report.to_dict()['summary']

        self.assertEqual({'collected': 4, 'succeeded': 2, 'skipped': 1, 'failed': 1}, summary)

    def test_aborted_counts_as_failed(self):
        self.assertEqual(1, make_report(ABORTED).to_dict()['summary']['failed'])


class TruncationTest(unittest.TestCase):

    def test_failures_survive_truncation(self):
        # SNS caps a message at 256KB, and the failures are what an operator needs, so they
        # must not be the ones dropped
        report = make_report(*(['OK'] * (MAX_ENTRIES + 50) + ['ERROR'] * 3))
        payload = report.to_dict()

        self.assertEqual(MAX_ENTRIES, len(payload['entries']))
        self.assertEqual(53, payload['entries_omitted'])
        self.assertEqual(3, len([e for e in payload['entries'] if e['status'] == 'ERROR']))

    def test_summary_stays_complete_when_truncated(self):
        report = make_report(*(['OK'] * (MAX_ENTRIES + 50) + ['ERROR'] * 3))
        summary = report.to_dict()['summary']
        self.assertEqual(MAX_ENTRIES + 50, summary['succeeded'])
        self.assertEqual(3, summary['failed'])

    def test_nothing_omitted_under_the_cap(self):
        self.assertEqual(0, make_report('OK', 'ERROR').to_dict()['entries_omitted'])


class SerialisationTest(unittest.TestCase):

    def test_report_is_json_serialisable(self):
        report = make_report('OK', 'ERROR')
        report.collected = 2
        json.loads(json.dumps(report.to_dict()))

    def test_timestamps_are_iso8601_utc(self):
        self.assertTrue(make_report().to_dict()['started_at'].endswith('Z'))


class DescribeErrorTest(unittest.TestCase):

    def test_none_returns_none(self):
        self.assertIsNone(describe_error(None))

    def test_plain_exception(self):
        self.assertEqual('ValueError: bad value', describe_error(ValueError('bad value')))

    def test_client_error_leads_with_the_aws_error_code(self):
        error = ClientError({'Error': {'Code': 'InvalidDBInstanceState',
                                       'Message': 'not available'}}, 'CreateDBSnapshot')
        self.assertTrue(describe_error(error).startswith('InvalidDBInstanceState: '))

    def test_an_exception_whose_str_raises_is_still_described(self):
        class Awkward(Exception):
            def __str__(self):
                raise RuntimeError('even __str__ is broken')

        self.assertIsNotNone(describe_error(Awkward()))


if __name__ == '__main__':
    unittest.main()
