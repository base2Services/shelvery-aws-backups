import abc
import logging
import time
import sys

import botocore
import yaml
import boto3
from botocore.exceptions import ClientError
from datetime import datetime

from typing import List, Dict
from abc import abstractmethod
from abc import abstractclassmethod

from shelvery.notifications import ShelveryNotification
from shelvery.aws_helper import AwsHelper
from shelvery.shelvery_invoker import ShelveryInvoker
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.entity_resource import EntityResource

from shelvery import LAMBDA_WAIT_ITERATION
from shelvery import S3_DATA_PREFIX
from shelvery import SHELVERY_DO_BACKUP_TAGS


class ShelveryEngine:
    """Base class for all backup processing, contains logic"""

    __metaclass__ = abc.ABCMeta

    DEFAULT_KEEP_DAILY = 14
    DEFAULT_KEEP_WEEKLY = 8
    DEFAULT_KEEP_MONTHLY = 12
    DEFAULT_KEEP_YEARLY = 10

    BACKUP_RESOURCE_TAG = 'create_backup'

    def __init__(self):
        # system logger
        FORMAT = "%(asctime)s %(process)s %(thread)s: %(message)s"
        logging.basicConfig(format=FORMAT)
        logging.info("Initialize logger")
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)
        self.aws_request_id = 0
        self.lambda_wait_iteration = 0
        self.lambda_payload = None
        self.lambda_context = None
        self.role_arn = None
        self.role_external_id = None
        self.account_id = AwsHelper.local_account_id()
        self.region = AwsHelper.local_region()
        self.snspublisher = ShelveryNotification(RuntimeConfig.get_sns_topic(self))
        self.snspublisher_error = ShelveryNotification(RuntimeConfig.get_error_sns_topic(self))

    def set_lambda_environment(self, payload, context):
        self.lambda_payload   = payload
        self.lambda_context   = context
        self.aws_request_id   = context.aws_request_id
        self.role_arn         = RuntimeConfig.get_role_arn(self)
        self.role_external_id = RuntimeConfig.get_role_external_id(self)
        if ('arguments' in payload) and (LAMBDA_WAIT_ITERATION in payload['arguments']):
            self.lambda_wait_iteration = payload['arguments'][LAMBDA_WAIT_ITERATION]

    def get_bucket_name(self, account_id=None, region=None):
        if account_id is None:
            account_id = self.account_id
        if region is None:
            region = self.region
        template = RuntimeConfig.get_bucket_name_template(self)
        return template.format(account_id=account_id, region=region)

    def get_local_bucket_name(self, region=None):
        return self.get_bucket_name(region=region)

    def get_remote_bucket_name(self, account_id, remote_region=None):
        return self.get_bucket_name(account_id=account_id, region=remote_region)

    def _get_data_bucket(self, region=None):
        bucket_name = self.get_local_bucket_name(region)
        if region is None:
            loc_constraint = boto3.session.Session().region_name
        else:
            loc_constraint = region

        s3 = boto3.resource('s3')
        try:
            AwsHelper.boto3_client('s3').head_bucket(Bucket=bucket_name)
            bucket = s3.Bucket(bucket_name)

        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                client_region = loc_constraint
                s3client = AwsHelper.boto3_client('s3', region_name=client_region)
                if loc_constraint == "us-east-1":
                    bucket = s3client.create_bucket(Bucket=bucket_name)
                else:
                    if loc_constraint == "eu-west-1":
                        loc_constraint = "EU"

                    bucket = s3client.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={
                        'LocationConstraint': loc_constraint
                    })

                # store the bucket policy, so the bucket can be accessed from other accounts
                # that backups are shared with
                s3client.put_bucket_policy(Bucket=bucket_name,
                                           Policy=AwsHelper.get_shelvery_bucket_policy(
                                               self.account_id,
                                               RuntimeConfig.get_share_with_accounts(self),
                                               bucket_name)
                                           )
                return s3.Bucket(bucket_name)
            else:
                raise e
        return bucket

    def _archive_backup_metadata(self, backup, bucket, shared_accounts=[]):
        s3key = f"{S3_DATA_PREFIX}/{self.get_engine_type()}/{backup.name}.yaml"
        s3archive_key = f"{S3_DATA_PREFIX}/{self.get_engine_type()}/removed/{backup.name}.yaml"
        bucket.put_object(
            Key=s3archive_key,
            Body=yaml.dump(backup, default_flow_style=False)
        )
        bucket.Object(s3key).delete()
        self.logger.info(f"Deleted data for backup {backup.name} from s3://{bucket.name}/{s3key}")

        for shared_account_id in shared_accounts:
            s3shared_key = f"{S3_DATA_PREFIX}/shared/{shared_account_id}/{self.get_engine_type()}/{backup.name}.yaml"
            bucket.Object(s3shared_key).delete()
            self.logger.info(f"Deleted data for shared backup {backup.name} from s3://{bucket.name}/{s3shared_key}")


        self.logger.info(f"Archived data for backup {backup.name} of type {self.get_engine_type()} to" +
                         f" s3://{bucket.name}/{s3archive_key}")

    def _write_backup_data(self, backup, bucket, shared_account_id=None):
        s3key = f"{S3_DATA_PREFIX}/{self.get_engine_type()}/{backup.name}.yaml"
        if shared_account_id is not None:
            s3key = f"{S3_DATA_PREFIX}/shared/{shared_account_id}/{self.get_engine_type()}/{backup.name}.yaml"
        bucket.put_object(
            Body=yaml.dump(backup, default_flow_style=False),
            Key=s3key
        )
        self.logger.info(f"Wrote meta for backup {backup.name} of type {self.get_engine_type()} to" +
                         f" s3://{bucket.name}/{s3key}")


    ### Top level methods, invoked externally ####
    def create_backups(self) -> List[BackupResource]:
        """Create backups from all collected entities marked for backup by using specific tag"""

        # collect resources to be backed up
        resource_type = self.get_resource_type()
        self.logger.info(f"Collecting entities of type {resource_type} tagged with "
                         f"{RuntimeConfig.get_tag_prefix()}:{self.BACKUP_RESOURCE_TAG}")
        resources = self.get_entities_to_backup(f"{RuntimeConfig.get_tag_prefix()}:{self.BACKUP_RESOURCE_TAG}")

        # allows user to select single entity to be backed up
        if RuntimeConfig.get_shelvery_select_entity(self) is not None:
            entity_id = RuntimeConfig.get_shelvery_select_entity(self)
            self.logger.info(f"Creating backups only for entity {entity_id}")
            resources = list(
                filter(
                    lambda x: x.resource_id == entity_id,
                    resources)
            )

        self.logger.info(f"{len(resources)} resources of type {resource_type} collected for backup")

        # create and collect backups
        backup_resources = []
        current_retention_type = RuntimeConfig.get_current_retention_type(self)
        for r in resources:
            backup_resource = BackupResource(
                tag_prefix=RuntimeConfig.get_tag_prefix(),
                entity_resource=r,
                copy_resource_tags=RuntimeConfig.copy_resource_tags(self),
                exluded_resource_tag_keys=RuntimeConfig.get_exluded_resource_tag_keys(self)
            )
            # if retention is explicitly given by runtime environment
            if current_retention_type is not None:
                backup_resource.set_retention_type(current_retention_type)

            dr_regions = RuntimeConfig.get_dr_regions(backup_resource.entity_resource.tags, self)
            backup_resource.tags[f"{RuntimeConfig.get_tag_prefix()}:dr_regions"] = ','.join(dr_regions)
            self.logger.info(f"Processing {resource_type} with id {r.resource_id}")
            self.logger.info(f"Creating backup {backup_resource.name}")
            try:
                self.backup_resource(backup_resource)
                self.tag_backup_resource(backup_resource)
                self.logger.info(f"Created backup of type {resource_type} for entity {backup_resource.entity_id} "
                                 f"with id {backup_resource.backup_id}")
                backup_resources.append(backup_resource)
                self.store_backup_data(backup_resource)
                self.snspublisher.notify({
                    'Operation': 'CreateBackup',
                    'Status': 'OK',
                    'BackupType': self.get_engine_type(),
                    'BackupName': backup_resource.name,
                    'EntityId': backup_resource.entity_id
                })
            except ClientError as e:
                if e.response['Error']['Code'] == 'InvalidDBInstanceState':
                    if RuntimeConfig.ignore_invalid_resource_state():
                        self.logger.warn(f"{backup_resource.name} of type {resource_type} is not in a state a backup can be taken")
                    else:
                        self.snspublisher_error.notify({
                            'Operation': 'CreateBackup',
                            'Status': 'ERROR',
                            'ExceptionInfo': e.__dict__,
                            'BackupType': self.get_engine_type(),
                            'BackupName': backup_resource.name,
                            'EntityId': backup_resource.entity_id
                        })
                        self.logger.exception(f"Failed to create backup {backup_resource.name}:{e}")
                else:
                    self.snspublisher_error.notify({
                        'Operation': 'CreateBackup',
                        'Status': 'ERROR',
                        'ExceptionInfo': e.__dict__,
                        'BackupType': self.get_engine_type(),
                        'BackupName': backup_resource.name,
                        'EntityId': backup_resource.entity_id
                    })
                    self.logger.exception(f"Failed to create backup {backup_resource.name}:{e}")

        # create backups and disaster recovery region
        for br in backup_resources:
            self.copy_backup(br, RuntimeConfig.get_dr_regions(br.entity_resource.tags, self))

        for aws_account_id in RuntimeConfig.get_share_with_accounts(self):
            for br in backup_resources:
                self.share_backup(br, aws_account_id)

        return backup_resources

    def clean_backups(self):
        # collect backups
        existing_backups = self.get_existing_backups(RuntimeConfig.get_tag_prefix())

        # allows user to select single entity backups to be cleaned
        if RuntimeConfig.get_shelvery_select_entity(self) is not None:
            entity_id = RuntimeConfig.get_shelvery_select_entity(self)
            self.logger.info(f"Checking only for backups of entity {entity_id}")
            existing_backups = list(
                filter(
                    lambda x: x.entity_id == entity_id,
                    existing_backups)
            )

        self.logger.info(f"Collected {len(existing_backups)} backups to be checked for expiry date")
        self.logger.info(f"""Using following retention settings from runtime environment (resource overrides enabled):
                            Keeping last {RuntimeConfig.get_keep_daily(None, self)} daily backups
                            Keeping last {RuntimeConfig.get_keep_weekly(None, self)} weekly backups
                            Keeping last {RuntimeConfig.get_keep_monthly(None, self)} monthly backups
                            Keeping last {RuntimeConfig.get_keep_yearly(None, self)} yearly backups""")

        # check backups for expire date, delete if necessary
        for backup in existing_backups:
            self.logger.info(f"Checking backup {backup.backup_id}")
            try:
                if backup.is_stale(self, RuntimeConfig.get_custom_retention_types(self)):
                    self.logger.info(
                        f"{backup.retention_type} backup {backup.name} has expired on {backup.expire_date}, cleaning up")
                    self.delete_backup(backup)
                    backup.date_deleted = datetime.utcnow()
                    self._archive_backup_metadata(backup, self._get_data_bucket(), RuntimeConfig.get_share_with_accounts(self))
                    self.snspublisher.notify({
                        'Operation': 'DeleteBackup',
                        'Status': 'OK',
                        'BackupType': self.get_engine_type(),
                        'BackupName': backup.name,
                    })
                else:
                    self.logger.info(f"{backup.retention_type} backup {backup.name} is valid "
                                     f"until {backup.expire_date}, keeping this backup")
            except Exception as e:
                self.snspublisher_error.notify({
                    'Operation': 'DeleteBackup',
                    'Status': 'ERROR',
                    'ExceptionInfo': e.__dict__,
                    'BackupType': self.get_engine_type(),
                    'BackupName': backup.name,
                })
                self.logger.exception(f"Error checking backup {backup.backup_id} for cleanup: {e}")

    def pull_shared_backups(self):

        account_id = self.account_id
        s3_client = AwsHelper.boto3_client('s3')
        for src_account_id in RuntimeConfig.get_source_backup_accounts(self):
            try:
                bucket_name = self.get_remote_bucket_name(src_account_id)
                path = f"backups/shared/{account_id}/{self.get_engine_type()}/"
                path_processed = f"backups/shared/{account_id}/{self.get_engine_type()}-processed"
                path_failed = f"backups/shared/{account_id}/{self.get_engine_type()}-failed"
                bucket_loc = s3_client.get_bucket_location(Bucket=bucket_name)
                bucket_region = bucket_loc['LocationConstraint']
                if bucket_region == 'EU':
                    bucket_region = 'eu-west-1'
                elif bucket_region is None:
                    bucket_region = 'us-east-1'
                regional_client = AwsHelper.boto3_client('s3', region_name=bucket_region)

                shared_backups = regional_client.list_objects_v2(Bucket=bucket_name, Prefix=path)
                if 'Contents' in shared_backups:
                    all_backups = shared_backups['Contents']
                else:
                    self.logger.info(f"No shared backups of type {self.get_engine_type()} found to pull")
                    all_backups = {}
                while 'NextContinuationToken' in shared_backups:
                    shared_backups = regional_client.list_objects_v2(
                        Bucket=bucket_name, Delimiter='/',
                        Prefix=path, ContinuationToken=shared_backups['NextContinuationToken']
                    )
                    all_backups.extend(shared_backups['Contents'])

                for backup_object in all_backups:
                    try:
                        serialised_shared_backup = regional_client.get_object(
                            Bucket=bucket_name,
                            Key=backup_object['Key'])['Body'].read()
                        shared_backup = yaml.load(serialised_shared_backup)
                        new_backup_id = self.copy_shared_backup(src_account_id, shared_backup)
                        new_backup = shared_backup.cross_account_copy(new_backup_id)
                        self.tag_backup_resource(new_backup)
                        self.store_backup_data(new_backup)
                        regional_client.delete_object(Bucket=bucket_name, Key=backup_object['Key'])
                        self.logger.info(f"Removed s3://{bucket_name}/{backup_object['Key']}")
                        regional_client.put_object(
                            Bucket=bucket_name,
                            Key=f"{path_processed}/{shared_backup.name}.yaml",
                            Body=yaml.dump(shared_backup, default_flow_style=False)
                        )
                        self.logger.info(
                            f"Moved shared backup info to s3://{bucket_name}/{path_processed}/{shared_backup.name}.yaml")
                        self.snspublisher.notify({
                            'Operation': 'PullSharedBackup',
                            'Status': 'OK',
                            'BackupType': self.get_engine_type(),
                            'SourceAccount': src_account_id,
                            'Backup': shared_backup.name
                        })
                    except Exception as e:
                        backup_name = backup_object['Key'].split('/')[-1].replace('.yaml', '')
                        self.logger.exception(f"Failed to copy shared backup s3://{bucket_name}/{backup_object['Key']}")
                        self.snspublisher_error.notify({
                            'Operation': 'PullSharedBackup',
                            'Status': 'ERROR',
                            'ExceptionInfo': e.__dict__,
                            'BackupType': self.get_engine_type(),
                            'SourceAccount': src_account_id,
                            'BackupS3Location': backup_object['Key'],
                            'NewS3Location': f"{path_failed}/{backup_name}.yaml",
                            'Bucket': bucket_name
                        })
                        regional_client.put_object(
                            Bucket=bucket_name,
                            Key=f"{path_failed}/{backup_name}.yaml",
                            Body=yaml.dump(shared_backup, default_flow_style=False)
                        )
                        self.logger.info(
                            f"Failed share backup operation | backup info moved to s3://{bucket_name}/{path_failed}/{shared_backup.name}.yaml ")

            except Exception as e:
                self.snspublisher_error.notify({
                    'Operation': 'PullSharedBackupsFromAccount',
                    'Status': 'ERROR',
                    'ExceptionInfo': e.__dict__,
                    'BackupType': self.get_engine_type(),
                    'SourceAccount': src_account_id,
                })
                self.logger.exception("Failed to pull shared backups")

    def create_data_buckets(self):
        regions = [self.region]
        regions.extend(RuntimeConfig.get_dr_regions(None, self))
        for region in regions:
            bucket = self._get_data_bucket(region)
            AwsHelper.boto3_client('s3', region_name=region).put_bucket_policy(Bucket=bucket.name,
                                                 Policy=AwsHelper.get_shelvery_bucket_policy(
                                                     self.account_id,
                                                     RuntimeConfig.get_share_with_accounts(self),
                                                     bucket.name)
                                                 )

    ### Helper methods, invoked internally, could be refactored
    def do_wait_backup_available(self, backup_region: str, backup_id: str, timeout_fn=None):
        """Wait for backup to become available. Additionally pass on timeout function
            to be executed if code is running in lambda environment, and remaining execution
            time is lower than threshold of 20 seconds"""

        total_wait_time = 0
        retry = 15
        timeout = RuntimeConfig.get_wait_backup_timeout(self)
        self.logger.info(f"Waiting for backup {backup_id} to become available, timing out after {timeout} seconds...")

        available = self.is_backup_available(backup_region, backup_id)
        while not available:
            if total_wait_time >= timeout or total_wait_time + retry > timeout:
                timeout_fn()
                raise Exception(f"Backup {backup_id} did not become available in {timeout} seconds")
            self.logger.info(f"Sleeping for {retry} seconds until backup {backup_id} becomes available")
            time.sleep(retry)
            total_wait_time = total_wait_time + retry
            available = self.is_backup_available(backup_region, backup_id)

    def wait_backup_available(self, backup_region: str, backup_id: str, lambda_method: str, lambda_args: Dict) -> bool:
        """Wait for backup to become available. If running in lambda environment, pass lambda method and
            arguments to be executed if lambda functions times out, and return false. Always return true
            in non-lambda mode"""
        has_timed_out = {'value': False}
        engine = self

        def call_recursively():
            # check if exceeded allowed number of wait iterations in lambda
            if self.lambda_wait_iteration > RuntimeConfig.get_max_lambda_wait_iterations():
                raise Exception(f"Reached maximum of {RuntimeConfig.get_max_lambda_wait_iterations()} lambda wait"
                                f"operations")

            lambda_args['lambda_wait_iteration'] = self.lambda_wait_iteration + 1
            if lambda_method is not None and lambda_args is not None:
                ShelveryInvoker().invoke_shelvery_operation(
                    engine,
                    method_name=lambda_method,
                    method_arguments=lambda_args)
            has_timed_out['value'] = True

        def panic():
            self.logger.error(f"Failed to wait for backup to become available, exiting...")
            sys.exit(-5)

        # if running in lambda environment, call function recursively on timeout
        # otherwise in cli mode, just exit
        timeout_fn = call_recursively if RuntimeConfig.is_lambda_runtime(self) else panic
        self.do_wait_backup_available(backup_region=backup_region, backup_id=backup_id, timeout_fn=timeout_fn)
        return not (has_timed_out['value'] and RuntimeConfig.is_lambda_runtime(self))

    def copy_backup(self, backup_resource: BackupResource, target_regions: List[str]):
        """Copy backup to set of regions - this is orchestration method, rather than
            logic implementation"""
        method = 'do_copy_backup'

        # call lambda recursively for each backup / region pair
        for region in target_regions:
            arguments = {
                'OriginRegion': backup_resource.region,
                'BackupId': backup_resource.backup_id,
                'Region': region
            }
            ShelveryInvoker().invoke_shelvery_operation(self, method, arguments)

    def share_backup(self, backup_resource: BackupResource, aws_account_id: str):
        """
        Share backup with other AWS account - this is orchestration method, rather than
        logic implementation, invokes actual implementation or lambda
        """

        method = 'do_share_backup'
        arguments = {
            'Region': backup_resource.region,
            'BackupId': backup_resource.backup_id,
            'AwsAccountId': aws_account_id
        }
        ShelveryInvoker().invoke_shelvery_operation(self, method, arguments)

    def do_copy_backup(self, map_args={}, **kwargs):
        """
        Copy backup to another region, actual implementation
        """

        kwargs.update(map_args)
        backup_id = kwargs['BackupId']
        origin_region = kwargs['OriginRegion']
        backup_resource = self.get_backup_resource(origin_region, backup_id)
        # if backup is not available, exit and rely on recursive lambda call copy backup
        # in non lambda mode this should never happen
        if RuntimeConfig.is_offload_queueing(self):
            if not self.is_backup_available(origin_region,backup_id):
                self.copy_backup(self.get_backup_resource(backup_resource, RuntimeConfig.get_dr_regions(backup_resource.entity_resource.tags, self)))
        else:
            if not self.wait_backup_available(backup_region=origin_region,
                                              backup_id=backup_id,
                                              lambda_method='do_copy_backup',
                                              lambda_args=kwargs):
                return

        self.logger.info(f"Do copy backup {kwargs['BackupId']} ({kwargs['OriginRegion']}) to region {kwargs['Region']}")

        # copy backup
        try:
            src_region = kwargs['OriginRegion']
            dst_region = kwargs['Region']
            regional_backup_id = self.copy_backup_to_region(kwargs['BackupId'], dst_region)

            # create tags on backup copy
            original_backup_id = kwargs['BackupId']
            original_backup = self.get_backup_resource(src_region, original_backup_id)
            resource_copy = BackupResource(None, None, True)
            resource_copy.backup_id = regional_backup_id
            resource_copy.region = kwargs['Region']
            resource_copy.tags = original_backup.tags.copy()

            # add metadata to dr copy and original
            dr_copies_tag_key = f"{RuntimeConfig.get_tag_prefix()}:dr_copies"
            resource_copy.tags[f"{RuntimeConfig.get_tag_prefix()}:region"] = dst_region
            resource_copy.tags[f"{RuntimeConfig.get_tag_prefix()}:dr_copy"] = 'true'
            resource_copy.tags[
                f"{RuntimeConfig.get_tag_prefix()}:dr_source_backup"] = f"{src_region}:{original_backup_id}"

            if dr_copies_tag_key not in original_backup.tags:
                original_backup.tags[dr_copies_tag_key] = ''
            original_backup.tags[dr_copies_tag_key] = original_backup.tags[
                                                          dr_copies_tag_key] + f"{dst_region}:{regional_backup_id} "

            self.tag_backup_resource(resource_copy)
            self.tag_backup_resource(original_backup)
            self.snspublisher.notify({
                'Operation': 'CopyBackupToRegion',
                'Status': 'OK',
                'DestinationRegion': kwargs['Region'],
                'BackupType': self.get_engine_type(),
                'BackupId': kwargs['BackupId'],
            })
            self.store_backup_data(resource_copy)
        except Exception as e:
            self.snspublisher_error.notify({
                'Operation': 'CopyBackupToRegion',
                'Status': 'ERROR',
                'ExceptionInfo': e.__dict__,
                'DestinationRegion': kwargs['Region'],
                'BackupType': self.get_engine_type(),
                'BackupId': kwargs['BackupId'],
            })
            self.logger.exception(f"Error copying backup {kwargs['BackupId']} to {dst_region}")

        # shared backup copy with same accounts
        for shared_account_id in RuntimeConfig.get_share_with_accounts(self):
            backup_resource = BackupResource(None, None, True)
            backup_resource.backup_id = regional_backup_id
            backup_resource.region = kwargs['Region']
            try:
                self.share_backup(backup_resource, shared_account_id)
                self.snspublisher.notify({
                    'Operation': 'ShareRegionalBackupCopy',
                    'Status': 'OK',
                    'DestinationAccount': shared_account_id,
                    'DestinationRegion': kwargs['Region'],
                    'BackupType': self.get_engine_type(),
                    'BackupId': kwargs['BackupId'],
                })
            except Exception as e:
                self.snspublisher_error.notify({
                    'Operation': 'ShareRegionalBackupCopy',
                    'Status': 'ERROR',
                    'DestinationAccount': shared_account_id,
                    'DestinationRegion': kwargs['Region'],
                    'ExceptionInfo': e.__dict__,
                    'BackupType': self.get_engine_type(),
                    'BackupId': kwargs['BackupId'],
                })
                self.logger.exception(f"Error sharing copied backup {kwargs['BackupId']} to {dst_region}")

    def do_share_backup(self, map_args={}, **kwargs):
        """Share backup with other AWS account, actual implementation"""
        kwargs.update(map_args)
        backup_id = kwargs['BackupId']
        backup_region = kwargs['Region']
        destination_account_id = kwargs['AwsAccountId']
        backup_resource = self.get_backup_resource(backup_region, backup_id)
        # if backup is not available, exit and rely on recursive lambda call do share backup
        # in non lambda mode this should never happen
        if RuntimeConfig.is_offload_queueing(self):
            if not self.is_backup_available(backup_region, backup_id):
                self.share_backup(backup_resource, destination_account_id)
        else:
            if not self.wait_backup_available(backup_region=backup_region,
                                              backup_id=backup_id,
                                              lambda_method='do_share_backup',
                                              lambda_args=kwargs):
                return

        self.logger.info(f"Do share backup {backup_id} ({backup_region}) with {destination_account_id}")
        try:
            self.share_backup_with_account(backup_region, backup_id, destination_account_id)
            backup_resource = self.get_backup_resource(backup_region, backup_id)
            self._write_backup_data(
                backup_resource,
                self._get_data_bucket(backup_region),
                destination_account_id
            )
            self.snspublisher.notify({
                'Operation': 'ShareBackup',
                'Status': 'OK',
                'BackupType': self.get_engine_type(),
                'BackupName': backup_resource.name,
                'DestinationAccount': kwargs['AwsAccountId']
            })
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidDBSnapshotState':
                # This will occasionally happen due to AWS eventual consistency model
                self.logger.warn(f"Retrying to share backup {backup_id} ({backup_region}) with account {destination_account_id} due to exception InvalidDBSnapshotState")
                self.share_backup(backup_resource, destination_account_id)
            else:
                self.snspublisher_error.notify({
                    'Operation': 'ShareBackup',
                    'Status': 'ERROR',
                    'ExceptionInfo': e.__dict__,
                    'BackupType': self.get_engine_type(),
                    'BackupId': backup_id,
                    'DestinationAccount': kwargs['AwsAccountId']
                })
                self.logger.exception(
                    f"Failed to share backup {backup_id} ({backup_region}) with account {destination_account_id}")

    def store_backup_data(self, backup_resource: BackupResource):
        """
        Top level method to save backup data to s3 bucket.
        Invokes thread / lambda to wait until backup becomes available and only then
        the metadata is written to the bucket
        :param backup_resource:
        :return:
        """
        method = 'do_store_backup_data'
        arguments = {
            'BackupId': backup_resource.backup_id,
            'BackupRegion': backup_resource.region
        }

        ShelveryInvoker().invoke_shelvery_operation(self, method, arguments)

    def do_store_backup_data(self, map_args={}, **kwargs):
        """
        Actual logic for writing backup resource data to s3. Waits for backup
        availability
        :param map_args:
        :param kwargs:
        :return:
        """
        kwargs.update(map_args)
        backup_id = kwargs['BackupId']
        backup_region = kwargs['BackupRegion']
        backup_resource = self.get_backup_resource(backup_region, backup_id)
        # if backup is not available, exit and rely on recursive lambda call write metadata
        # in non lambda mode this should never happen
        if RuntimeConfig.is_offload_queueing(self):
            if not self.is_backup_available(backup_region, backup_id):
                self.store_backup_data(backup_resource)
        else:
            if not self.wait_backup_available(backup_region=backup_region,
                                              backup_id=backup_id,
                                              lambda_method='do_store_backup_data',
                                              lambda_args=kwargs):
                return

        if backup_resource.account_id is None:
            backup_resource.account_id = self.account_id
        bucket = self._get_data_bucket(backup_resource.region)
        self._write_backup_data(backup_resource, bucket)

    ####
    # Abstract methods, for engine implementations to implement
    ####

    @abstractmethod
    def copy_shared_backup(self, source_account: str, source_backup: BackupResource) -> str:
        """
        Copy Shelvery backup that has been shared from another account to account where
        shelvery is currently running
        :param source_account:
        :param source_backup:
        :return:
        """

    @abstractmethod
    def get_engine_type(self) -> str:
        """
        Return engine type, valid string to be passed to ShelveryFactory.get_shelvery_instance method
        """

    @abstractclassmethod
    def get_resource_type(self) -> str:
        """
        Returns entity type that's about to be backed up
        """

    @abstractmethod
    def delete_backup(self, backup_resource: BackupResource):
        """
        Remove given backup from system
        """

    @abstractmethod
    def get_existing_backups(self, backup_tag_prefix: str) -> List[BackupResource]:
        """
        Collect existing backups on system of given type, marked with given tag
        """

    @abstractmethod
    def get_entities_to_backup(self, tag_name: str) -> List[EntityResource]:
        """
        Returns list of objects with 'date_created', 'id' and 'tags' properties
        """
        return []

    @abstractmethod
    def backup_resource(self, backup_resource: BackupResource):
        """
        Returns list of objects with 'date_created', 'id' and 'tags' properties
        """
        return

    @abstractmethod
    def tag_backup_resource(self, backup_resource: BackupResource):
        """
        Create backup resource tags
        """

    @abstractmethod
    def copy_backup_to_region(self, backup_id: str, region: str) -> str:
        """
        Copy backup to another region
        """

    @abstractmethod
    def is_backup_available(self, backup_region: str, backup_id: str) -> bool:
        """
        Determine whether backup has completed and is available to be copied
        to other regions and shared with other ebs accounts
        """

    @abstractmethod
    def share_backup_with_account(self, backup_region: str, backup_id: str, aws_account_id: str):
        """
        Share backup with another AWS Account
        """

    @abstractmethod
    def get_backup_resource(self, backup_region: str, backup_id: str) -> BackupResource:
        """
        Get Backup Resource within region, identified by its backup_id
        """
