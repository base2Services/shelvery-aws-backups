from datetime import datetime
from typing import Dict

from dateutil.relativedelta import relativedelta
from datetime import timedelta

from shelvery.entity_resource import EntityResource
from shelvery.runtime_config import RuntimeConfig


class BackupResource:
    """Model representing single backup"""
    
    BACKUP_MARKER_TAG = 'backup'
    TIMESTAMP_FORMAT = '%Y-%m-%d-%H%M'
    
    RETENTION_DAILY = 'daily'
    RETENTION_WEEKLY = 'weekly'
    RETENTION_MONTHLY = 'monthly'
    RETENTION_YEARLY = 'yearly'
    
    def __init__(self, tag_prefix, entity_resource: EntityResource, construct=False):
        """Construct new backup resource out of entity resource (e.g. ebs volume)."""
        # if object manually created
        if construct:
            return
        
        # current date
        self.date_created = datetime.utcnow()
        
        # determine retention period
        if self.date_created.day == 1:
            if self.date_created.month == 1:
                self.retention_type = self.RETENTION_YEARLY
            else:
                self.retention_type = self.RETENTION_MONTHLY
        elif self.date_created.weekday() == 6:
            self.retention_type = self.RETENTION_WEEKLY
        else:
            self.retention_type = self.RETENTION_DAILY
        
        # determine backup name
        name = entity_resource.tags['Name'] if 'Name' in entity_resource.tags else entity_resource.resource_id
        date_formatted = self.date_created.strftime(self.TIMESTAMP_FORMAT)
        self.name = f"{name}-{date_formatted}-{self.retention_type}"
        
        self.tags = {
            'Name': self.name,
            "shelvery:tag_name": tag_prefix,
            f"{tag_prefix}:date_created": date_formatted,
            f"{tag_prefix}:name": self.name,
            f"{tag_prefix}:region": entity_resource.resource_region,
            f"{tag_prefix}:retention_type": self.retention_type,
            f"{tag_prefix}:{self.BACKUP_MARKER_TAG}": 'true'
        }
        self.backup_id = None
        self.expire_date = None
        
        self.entity_id = entity_resource.resource_id
        self.entity_resource = entity_resource
        self.__region = entity_resource.resource_region
    
    @classmethod
    def construct(cls,
                  tag_prefix: str,
                  backup_id: str,
                  tags: Dict):
        """
        Construct BackupResource object from object id and aws tags stored by shelvery
        """
        
        obj = BackupResource(None, None, True)
        obj.entity_resource = None
        obj.entity_id = None
        obj.backup_id = backup_id
        obj.tags = tags
        
        # read properties from tags
        obj.retention_type = tags[f"{tag_prefix}:retention_type"]
        obj.name = tags[f"{tag_prefix}:name"]
        obj.date_created = datetime.strptime(tags[f"{tag_prefix}:date_created"], cls.TIMESTAMP_FORMAT)
        obj.region = tags[f"{tag_prefix}:region"]
        return obj
    
    def calculate_expire_date(self, engine):
        """Determine expire date, based on 'retention_type' tag"""
        if self.retention_type == BackupResource.RETENTION_DAILY:
            expire_date = self.date_created + timedelta(
                days=RuntimeConfig.get_keep_daily(self.entity_resource.tags, engine))
        elif self.retention_type == BackupResource.RETENTION_WEEKLY:
            expire_date = self.date_created + relativedelta(
                weeks=RuntimeConfig.get_keep_weekly(self.entity_resource.tags, engine))
        elif self.retention_type == BackupResource.RETENTION_MONTHLY:
            expire_date = self.date_created + relativedelta(
                months=RuntimeConfig.get_keep_monthly(self.entity_resource.tags, engine))
        elif self.retention_type == BackupResource.RETENTION_YEARLY:
            expire_date = self.date_created + relativedelta(
                years=RuntimeConfig.get_keep_yearly(self.entity_resource.tags, engine))
        else:
            # in case there is no retention tag on backup, we want it kept forever
            expire_date = datetime.utcnow() + relativedelta(years=10)
        
        self.expire_date = expire_date
    
    def is_stale(self, engine):
        self.calculate_expire_date(engine)
        now = datetime.now(self.date_created.tzinfo)
        return now > self.expire_date
    
    @property
    def region(self):
        return self.__region
    
    @region.setter
    def region(self, region: str):
        self.__region = region
