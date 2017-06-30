import abc
import logging

from typing import List, Dict
from abc import abstractmethod
from abc import abstractclassmethod

from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.entity_resource import EntityResource
from datetime import datetime


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
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)
        logging.info("Initialize logger")
    
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
            self.tag_backup_resource(backup_resource.backup_id, backup_resource.tags)
            self.logger.info(f"Created backup of type {resource_type} for entity {backup_resource.entity_id} "
                             f"with id {backup_resource.backup_id}")
            backup_resources.append(backup_resource)
    
    def clean_backups(self):
        # collect backups
        existing_backups = self.get_existing_backups(RuntimeConfig.get_tag_prefix())
        self.logger.info(f"Collected {len(existing_backups)} backups to be checked for expiry date")
        self.logger.info(f"""Using following retention settings:
                            Keeping last {RuntimeConfig.get_keep_daily()} daily backups
                            Keeping last {RuntimeConfig.get_keep_weekly()} weekly backups
                            Keeping last {RuntimeConfig.get_keep_monthly()} monthly backups
                            Keeping last {RuntimeConfig.get_keep_yearly()} yearly backups""")
        
        # check backups for expire date, delete if necessary
        for backup in existing_backups:
            if backup.is_stale():
                self.logger.info(
                    f"{backup.retention_type} backup {backup.name} has expired on {backup.expire_date}, cleaning up")
                self.delete_backup(backup)
            else:
                self.logger.info(f"{backup.retention_type} backup {backup.name} is valid "
                                 f"until {backup.expire_date}, keeping this backup")
    
    @abstractclassmethod
    def get_resource_type(self) -> str:
        """Returns entity type that's about to be backed up"""
    
    @abstractmethod
    def delete_backup(self, backup_resource: BackupResource):
        """Remove given backup from system"""
    
    @abstractmethod
    def get_existing_backups(self, backup_tag_prefix: str) -> List[BackupResource]:
        """Collect existing backups on system of given type, marked with given tag"""
    
    @abstractmethod
    def get_entities_to_backup(self, tag_name: str) -> List[EntityResource]:
        """Returns list of objects with 'date_created', 'id' and 'tags' properties """
        return []
    
    @abstractmethod
    def backup_resource(self, backup_resource: BackupResource):
        """Returns list of objects with 'date_created', 'id' and 'tags' properties """
        return
    
    @abstractmethod
    def tag_backup_resource(self, backup_resource_id: str, tags: Dict):
        """Create backup resource tags"""
