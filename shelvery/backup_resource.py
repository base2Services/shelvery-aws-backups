import hashlib
import re
import copy
from datetime import datetime
from typing import Dict

from dateutil.relativedelta import relativedelta
from datetime import timedelta

from shelvery.aws_helper import AwsHelper
from shelvery.entity_resource import EntityResource
from shelvery.runtime_config import RuntimeConfig
import boto3

class BackupResource:
    """Model representing single backup"""

    BACKUP_MARKER_TAG = 'backup'
    TIMESTAMP_FORMAT = '%Y-%m-%d-%H%M'
    TIMESTAMP_FORMAT_LEGACY = '%Y%m%d-%H%M'

    RETENTION_DAILY = 'daily'
    RETENTION_WEEKLY = 'weekly'
    RETENTION_MONTHLY = 'monthly'
    RETENTION_YEARLY = 'yearly'

    def __init__(self, tag_prefix, entity_resource: EntityResource, construct=False, copy_resource_tags=True, exluded_resource_tag_keys=[]):
        """Construct new backup resource out of entity resource (e.g. ebs volume)."""
        # if object manually created
        if construct:
            return

        # current date
        self.date_created = datetime.utcnow()
        self.account_id = AwsHelper.local_account_id()

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

        # determine backup name. Hash of resource id is added to support creating backups
        # with resources having a same name
        if 'Name' in entity_resource.tags:
            name = entity_resource.tags['Name']
            name = name + '-' + hashlib.md5(entity_resource.resource_id.encode('utf-8')).hexdigest()[0:6]
        else:
            name = entity_resource.resource_id

        # replace anything that is not alphanumeric to hyphen
        # do not allow two hyphens next to each other
        name = re.sub('[^a-zA-Z0-9\-]', '-', name)
        name = re.sub('\-+','-',name)
        date_formatted = self.date_created.strftime(self.TIMESTAMP_FORMAT)
        self.name = f"{name}-{date_formatted}-{self.retention_type}"

        self.entity_id = entity_resource.resource_id
        self.entity_resource = entity_resource
        self.__region = entity_resource.resource_region

        self.tags = {
            'Name': self.name,
            "shelvery:tag_name": tag_prefix,
            f"{tag_prefix}:date_created": date_formatted,
            f"{tag_prefix}:src_account": self.account_id,
            f"{tag_prefix}:name": self.name,
            f"{tag_prefix}:region": entity_resource.resource_region,
            f"{tag_prefix}:retention_type": self.retention_type,
            f"{tag_prefix}:entity_id": entity_resource.resource_id,
            f"{tag_prefix}:{self.BACKUP_MARKER_TAG}": 'true'
        }

        if copy_resource_tags:
            for key, value in self.entity_resource_tags().items():
                if key == 'Name':
                    self.tags["ResourceName"] = value
                elif not any(exc_tag in key for exc_tag in exluded_resource_tag_keys):
                    self.tags[key] = value

        self.backup_id = None
        self.expire_date = None
        self.date_deleted = None

    def cross_account_copy(self, new_backup_id):
        backup = copy.deepcopy(self)

        # backup name and retention type are copied
        backup.backup_id = new_backup_id
        backup.region = AwsHelper.local_region()
        backup.account_id = AwsHelper.local_account_id()

        tag_prefix = self.tags['shelvery:tag_name']
        backup.tags[f"{tag_prefix}:region"] = backup.region
        backup.tags[f"{tag_prefix}:date_copied"] =  datetime.utcnow().strftime(self.TIMESTAMP_FORMAT)
        backup.tags[f"{tag_prefix}:dst_account"] = backup.account_id
        backup.tags[f"{tag_prefix}:src_region"] = self.region
        backup.tags[f"{tag_prefix}:region"] = backup.region
        backup.tags[f"{tag_prefix}:dr_copy"] = 'false'
        backup.tags[f"{tag_prefix}:cross_account_copy"] = 'true'
        backup.tags[f"{tag_prefix}:dr_regions"] = ''
        backup.tags[f"{tag_prefix}:dr_copies"] = ''
        return backup


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

        if f"{tag_prefix}:entity_id" in tags:
            obj.entity_id = tags[f"{tag_prefix}:entity_id"]

        try:
            obj.date_created = datetime.strptime(tags[f"{tag_prefix}:date_created"], cls.TIMESTAMP_FORMAT)
        except Exception as e:
            if 'does not match format' in str(e):
                str_date = tags[f"{tag_prefix}:date_created"]
                print(f"Failed to read {str_date} as date, trying legacy format {cls.TIMESTAMP_FORMAT_LEGACY}")
                obj.date_created = datetime.strptime(tags[f"{tag_prefix}:date_created"], cls.TIMESTAMP_FORMAT_LEGACY)


        obj.region = tags[f"{tag_prefix}:region"]
        if f"{tag_prefix}:src_account" in tags:
            obj.account_id = tags[f"{tag_prefix}:src_account"]
        else:
            obj.account_id = AwsHelper.local_account_id()

        return obj

    def entity_resource_tags(self):
        return self.entity_resource.tags if self.entity_resource is not None else {}

    def calculate_expire_date(self, engine, custom_retention_types=None):
        """Determine expire date, based on 'retention_type' tag"""
        if self.retention_type == BackupResource.RETENTION_DAILY:
            expire_date = self.date_created + timedelta(
                days=RuntimeConfig.get_keep_daily(self.entity_resource_tags(), engine))
        elif self.retention_type == BackupResource.RETENTION_WEEKLY:
            expire_date = self.date_created + relativedelta(
                weeks=RuntimeConfig.get_keep_weekly(self.entity_resource_tags(), engine))
        elif self.retention_type == BackupResource.RETENTION_MONTHLY:
            expire_date = self.date_created + relativedelta(
                months=RuntimeConfig.get_keep_monthly(self.entity_resource_tags(), engine))
        elif self.retention_type == BackupResource.RETENTION_YEARLY:
            expire_date = self.date_created + relativedelta(
                years=RuntimeConfig.get_keep_yearly(self.entity_resource_tags(), engine))
        elif self.retention_type in custom_retention_types:
            expire_date =  self.date_created + timedelta(
                seconds=custom_retention_types[self.retention_type])
        else:
            # in case there is no retention tag on backup, we want it kept forever
            expire_date = datetime.utcnow() + relativedelta(years=10)

        self.expire_date = expire_date

    def is_stale(self, engine, custom_retention_types = None):
        self.calculate_expire_date(engine, custom_retention_types)
        now = datetime.now(self.date_created.tzinfo)
        return now > self.expire_date

    @property
    def region(self):
        return self.__region

    @region.setter
    def region(self, region: str):
        self.__region = region

    def set_retention_type(self, retention_type: str):
        self.name = '-'.join(self.name.split('-')[0:-1]) + f"-{retention_type}"
        self.tags[f"{self.tags['shelvery:tag_name']}:name"] = self.name
        self.tags['Name'] = self.name
        self.tags[f"{self.tags['shelvery:tag_name']}:retention_type"] = retention_type

    @property
    def boto3_tags(self):
        tags = self.tags
        return list(map(lambda k: {'Key': k, 'Value': tags[k]}, tags))

    @staticmethod
    def dict_from_boto3_tags(boot3_tags):
        return dict(map(lambda t: (t['Key'], t['Value']), boot3_tags))
