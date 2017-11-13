import abc
import logging
import time
import sys

from typing import List, Dict
from abc import abstractmethod
from abc import abstractclassmethod

from shelvery.shelvery_invoker import ShelveryInvoker
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.entity_resource import EntityResource

LAMBDA_WAIT_ITERATION = 'lambda_wait_iteration'


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
    
    def set_lambda_environment(self, payload, context):
        self.lambda_payload = payload
        self.lambda_context = context
        self.aws_request_id = context.aws_request_id
        if ('arguments' in payload) and (LAMBDA_WAIT_ITERATION in payload['arguments']):
            self.lambda_wait_iteration = payload['arguments'][LAMBDA_WAIT_ITERATION]
    
    def create_backups(self):
        """Create backups from all collected entities marked for backup by using specific tag"""
        
        # collect resources to be backed up
        resource_type = self.get_resource_type()
        self.logger.info(f"Collecting entities of type {resource_type} tagged with "
                         f"{RuntimeConfig.get_tag_prefix()}:{self.BACKUP_RESOURCE_TAG}")
        resources = self.get_entities_to_backup(f"{RuntimeConfig.get_tag_prefix()}:{self.BACKUP_RESOURCE_TAG}")
        self.logger.info(f"{len(resources)} resources of type {resource_type} collected for backup")
        
        # create and collect backups
        backup_resources = []
        for r in resources:
            backup_resource = BackupResource(
                tag_prefix=RuntimeConfig.get_tag_prefix(),
                entity_resource=r
            )
            self.logger.info(f"Processing {resource_type} with id {r.resource_id}")
            self.logger.info(f"Creating backup {backup_resource.name}")
            self.backup_resource(backup_resource)
            self.tag_backup_resource(backup_resource)
            self.logger.info(f"Created backup of type {resource_type} for entity {backup_resource.entity_id} "
                             f"with id {backup_resource.backup_id}")
            backup_resources.append(backup_resource)
        
        # create backups and disaster recovery region
        for br in backup_resources:
            self.copy_backup(br, RuntimeConfig.get_dr_regions(br.entity_resource.tags, self))
        
        for aws_account_id in RuntimeConfig.get_share_with_accounts(self):
            for br in backup_resources:
                self.share_backup(br, aws_account_id)
    
    def clean_backups(self):
        # collect backups
        existing_backups = self.get_existing_backups(RuntimeConfig.get_tag_prefix())
        self.logger.info(f"Collected {len(existing_backups)} backups to be checked for expiry date")
        self.logger.info(f"""Using following retention settings from runtime environment (resource overrides enabled):
                            Keeping last {RuntimeConfig.get_keep_daily(None, self)} daily backups
                            Keeping last {RuntimeConfig.get_keep_weekly(None, self)} weekly backups
                            Keeping last {RuntimeConfig.get_keep_monthly(None, self)} monthly backups
                            Keeping last {RuntimeConfig.get_keep_yearly(None, self)} yearly backups""")
        
        # check backups for expire date, delete if necessary
        for backup in existing_backups:
            if backup.is_stale(self):
                self.logger.info(
                    f"{backup.retention_type} backup {backup.name} has expired on {backup.expire_date}, cleaning up")
                self.delete_backup(backup)
            else:
                self.logger.info(f"{backup.retention_type} backup {backup.name} is valid "
                                 f"until {backup.expire_date}, keeping this backup")
    
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
        
        # tag source backup with dr regions
        backup_resource.tags[f"{RuntimeConfig.get_tag_prefix()}:dr_regions"] = ','.join(target_regions)
        self.tag_backup_resource(backup_resource)
        
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
        
        # if backup is not available, exit and rely on recursive lambda call copy backup
        # in non lambda mode this should never happen
        if not self.wait_backup_available(backup_region=kwargs['OriginRegion'],
                                          backup_id=kwargs['BackupId'],
                                          lambda_method='do_copy_backup',
                                          lambda_args=kwargs):
            return
        
        self.logger.info(f"Do copy backup {kwargs['BackupId']} ({kwargs['OriginRegion']}) to region {kwargs['Region']}")
        
        # copy backup
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
        resource_copy.tags[f"{RuntimeConfig.get_tag_prefix()}:dr_source_backup"] = f"{src_region}:{original_backup_id}"
        
        if dr_copies_tag_key not in original_backup.tags:
            original_backup.tags[dr_copies_tag_key] = ''
        original_backup.tags[dr_copies_tag_key] = original_backup.tags[
                                                      dr_copies_tag_key] + f"{dst_region}:{regional_backup_id} "
        
        self.tag_backup_resource(resource_copy)
        self.tag_backup_resource(original_backup)
        
        # shared backup copy with same accounts
        for shared_account_id in RuntimeConfig.get_share_with_accounts(self):
            backup_resource = BackupResource(None, None, True)
            backup_resource.backup_id = regional_backup_id
            backup_resource.region = kwargs['Region']
            self.share_backup(backup_resource, shared_account_id)
    
    def do_share_backup(self, map_args={}, **kwargs):
        """Share backup with other AWS account, actual implementation"""
        kwargs.update(map_args)
        
        # if backup is not available, exit and rely on recursive lambda call do share backup
        # in non lambda mode this should never happen
        if not self.wait_backup_available(backup_region=kwargs['Region'],
                                          backup_id=kwargs['BackupId'],
                                          lambda_method='do_share_backup',
                                          lambda_args=kwargs):
            return
        
        self.logger.info(f"Do share backup {kwargs['BackupId']} ({kwargs['Region']}) with {kwargs['AwsAccountId']}")
        self.share_backup_with_account(kwargs['Region'], kwargs['BackupId'], kwargs['AwsAccountId'])
    
    ####
    # Abstract methods, for engine implementations to implement
    ####
    
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
