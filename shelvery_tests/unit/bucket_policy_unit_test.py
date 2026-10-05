import json
import logging

from shelvery.aws_helper import AwsHelper
from shelvery.runtime_config import RuntimeConfig

OWNER = '111111111111'
SHARE = '222222222222'
BUCKET = f'shelvery.data.{OWNER}-ap-southeast-2.base2tools'

# Actions Security Hub S3.6 does not allow for other accounts.
S36_BLOCKED = {
    's3:DeleteBucketPolicy',
    's3:PutBucketAcl',
    's3:PutBucketPolicy',
    's3:PutEncryptionConfiguration',
    's3:PutObjectAcl',
}


def _statements(share_ids):
    return json.loads(AwsHelper.get_shelvery_bucket_policy(OWNER, share_ids, BUCKET))['Statement']


def _actions(stmt):
    action = stmt['Action']
    return [action] if isinstance(action, str) else action


def test_share_account_has_no_wildcard_or_s36_blocked_actions():
    for stmt in _statements([SHARE]):
        if SHARE not in stmt['Principal']['AWS']:
            continue
        for action in _actions(stmt):
            assert action != 's3:*'
            assert action not in S36_BLOCKED


def test_share_account_can_pull_its_own_prefix():
    stmts = [s for s in _statements([SHARE]) if SHARE in s['Principal']['AWS']]
    object_stmt = next(s for s in stmts if s['Resource'].endswith('/*'))
    assert object_stmt['Resource'] == f'arn:aws:s3:::{BUCKET}/backups/shared/{SHARE}/*'
    assert set(_actions(object_stmt)) == {'s3:GetObject', 's3:PutObject', 's3:DeleteObject'}


def test_no_share_accounts_leaves_owner_statement_only():
    stmts = _statements([])
    assert len(stmts) == 1
    assert stmts[0]['Principal']['AWS'] == f'arn:aws:iam::{OWNER}:root'


def test_share_actions_can_be_overridden():
    policy = AwsHelper.get_shelvery_bucket_policy(OWNER, [SHARE], BUCKET, ['s3:*'])
    object_stmt = json.loads(policy)['Statement'][2]
    assert object_stmt['Action'] == ['s3:*']
    assert object_stmt['Resource'] == f'arn:aws:s3:::{BUCKET}/backups/shared/{SHARE}/*'


def _engine(lambda_payload=None):
    return type('Engine', (), {'lambda_payload': lambda_payload, 'logger': logging.getLogger('test')})()


def test_share_actions_runtime_config(monkeypatch):
    engine = _engine()
    monkeypatch.delenv('shelvery_share_bucket_policy_actions', raising=False)
    assert RuntimeConfig.get_share_bucket_policy_actions(engine) is None

    monkeypatch.setenv('shelvery_share_bucket_policy_actions', '')
    assert RuntimeConfig.get_share_bucket_policy_actions(engine) is None

    monkeypatch.setenv('shelvery_share_bucket_policy_actions', 's3:GetObject, s3:PutObject,s3:DeleteObject,s3:GetObjectTagging')
    assert RuntimeConfig.get_share_bucket_policy_actions(engine) == [
        's3:GetObject', 's3:PutObject', 's3:DeleteObject', 's3:GetObjectTagging']


def test_share_actions_accepts_list_in_lambda_payload(monkeypatch):
    monkeypatch.delenv('shelvery_share_bucket_policy_actions', raising=False)
    engine = _engine({'config': {'shelvery_share_bucket_policy_actions': ['s3:GetObject', 's3:PutObject']}})
    assert RuntimeConfig.get_share_bucket_policy_actions(engine) == ['s3:GetObject', 's3:PutObject']


def test_invalid_share_actions_fall_back_to_default(monkeypatch):
    monkeypatch.setenv('shelvery_share_bucket_policy_actions', 's3:GetObject,GetObjct,s3:Put Object')
    assert RuntimeConfig.get_share_bucket_policy_actions(_engine()) is None
