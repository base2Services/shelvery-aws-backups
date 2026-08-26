"""Per-run backup status reporting.

Shelvery has always emitted a notification per backup operation, but nothing ever answered
"did tonight's run pass?". Every operation outcome is collected into a RunReport, which is
published to an optional SNS topic when the action finishes.

Nothing in here is allowed to break a backup run.
"""

import functools
import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SNS_SUBJECT = 'ShelveryRunReport'

# Entries reuse the status literals shelvery already puts on the wire: OK, ERROR, IGNORE.
# ABORTED is only ever set by the decorator below, when the action itself blew up.
ABORTED = 'ABORTED'

# SNS caps a message at 256KB and clean_backups walks every snapshot in the account, so the
# entry list is bounded. The summary counters stay complete.
MAX_ENTRIES = 500


def _now():
    return datetime.now(timezone.utc)


def _isoformat(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def describe_error(error):
    """Render an exception as a short string.

    ``e.__dict__`` is what the engine used to ship to SNS, and it can hold values json.dumps
    refuses. A ClientError's AWS error code is the useful part, so lead with it.
    """
    if error is None:
        return None

    code = None
    response = getattr(error, 'response', None)
    if isinstance(response, dict):
        code = response.get('Error', {}).get('Code')

    try:
        message = str(error)
    except Exception:
        message = repr(type(error).__name__)

    return f"{code}: {message}" if code else f"{type(error).__name__}: {message}"


class RunReport:
    """The outcome of a single shelvery action invocation."""

    def __init__(self, action, backup_type, account_id, region, run_id=None, version=None):
        self.action = action
        self.backup_type = backup_type
        self.account_id = account_id
        self.region = region
        self.run_id = run_id or str(uuid.uuid4())
        self.version = version
        self.started_at = _now()
        self.collected = 0
        self.entries = []

    def add(self, entry):
        self.entries.append(entry)

    def count(self, status):
        return sum(1 for e in self.entries if e['status'] == status)

    @property
    def status(self):
        if self.count(ABORTED) or (self.count('ERROR') and not self.count('OK')):
            return 'FAILED'
        if self.count('ERROR'):
            return 'PARTIAL'
        return 'OK'

    def to_dict(self):
        # keep failures in preference to successes when trimming
        entries = self.entries
        if len(entries) > MAX_ENTRIES:
            entries = ([e for e in entries if e['status'] != 'OK'] +
                       [e for e in entries if e['status'] == 'OK'])[:MAX_ENTRIES]

        return {
            'shelvery_version': self.version,
            'run_id': self.run_id,
            'account_id': self.account_id,
            'region': self.region,
            'backup_type': self.backup_type,
            'action': self.action,
            'started_at': _isoformat(self.started_at),
            'ended_at': _isoformat(_now()),
            'status': self.status,
            'summary': {
                'collected': self.collected,
                'succeeded': self.count('OK'),
                'skipped': self.count('IGNORE'),
                'failed': self.count('ERROR') + self.count(ABORTED),
            },
            'entries_omitted': len(self.entries) - len(entries),
            'entries': entries,
        }


def reported_action(fn):
    """Wrap a shelvery action so it always publishes a status report."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        self.start_run_report(fn.__name__)
        try:
            return fn(self, *args, **kwargs)
        except BaseException as e:
            # BaseException on purpose: the CLI timeout path calls sys.exit(), which raises
            # SystemExit. Record it, then let it propagate so the Lambda alarm still fires.
            self.report(fn.__name__, ABORTED, error=e)
            raise
        finally:
            self.publish_run_report()

    wrapper._shelvery_reported = True
    return wrapper
