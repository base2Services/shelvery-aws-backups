import re
import os
import boto3



class RuntimeConfig:
    """
    Helper to read runtime and other values
    Valid environment variables are

    shelvery_keep_daily_backups - daily backups to keep, defaults to 14 days
    shelvery_keep_weekly_backups - daily backups to keep, defaults to 8 weeks
    shelvery_keep_monthly_backups - daily backups to keep, defaults to 12 months
    shelvery_keep_yearly_backups - daily backups to keep, defaults to 10 years

    shelvery_custom_retention_types - custom retention periods in name:seconds format, comma separated, empty (disabled) by default
    shelvery_current_retention_type - custom retention period applied to current create backup process
    shelvery_dr_regions - disaster recovery regions, comma separated, empty (disabled) by default

    shelvery_keep_daily_backups_dr - daily backups to keep in disaster recover region
    shelvery_keep_weekly_backups_dr - daily backups to keep in disaster recover region
    shelvery_keep_monthly_backups_dr - daily backups to keep in disaster recover region
    shelvery_keep_yearly_backups_dr - daily backups to keep in disaster recover region

    shelvery_wait_snapshot_timeout - timeout in seconds to wait for snapshot to become available
                                    before copying it to another region / sharing with other account
                                    defaults to 1200

    shelvery_lambda_max_wait_iterations - maximum number of wait calls to lambda function. E.g.
                                        if lambda is set to timeout in 5 minutes, and this
                                        values is set to 3, total wait time will be approx 14 minutes,
                                        as lambda is invoked recursively 20 seconds before timeout
                                        defaults to 5

    shelvery_share_aws_account_ids - AWS Account Ids to share backups with. Applies to both original and regional
                                    backups

    shelvery_source_aws_account_ids - AWS Account Ids that are sharing shelvery backups with AWS Account shelvery
                                    is running in. Used for 'pull backups' feature

    shelvery_bucket_name_template - Template used to create bucket name. Available keys: `{account_id}`, `{region}`.
                                    Defaults to `shelvery.data.{account_id}-{region}.base2tools`

    shelvery_select_entity - Filter which entities get backed up, regardless of tags

    shelvery_sns_topic - SNS Topics for shelvery notifications

    shelvery_error_sns_topic - SNS Topics for just error messages

    shelvery_copy_resource_tags - Copy tags from original resource
    shelvery_exluded_resource_tag_keys - Comma separated list of tag keys to exclude from copying from original

    shelvery_sqs_queue_url - re invoke shelvery through a sqs queue

    shelvery_sqs_queue_wait_period - wait time in seconds before re invoking shelvery [0-900]

    shelvery_ignore_invalid_resource_state - ignore exceptions due to the resource being in a unavailable state,
                                             such as shutdown, rebooting.
    """

    DEFAULT_KEEP_DAILY = 14
    DEFAULT_KEEP_WEEKLY = 8
    DEFAULT_KEEP_MONTHLY = 12
    DEFAULT_KEEP_YEARLY = 10

    RDS_COPY_AUTOMATED_SNAPSHOT = 'RDS_COPY_AUTOMATED_SNAPSHOT'
    RDS_CREATE_SNAPSHOT = 'RDS_CREATE_SNAPSHOT'
    REDSHIFT_COPY_AUTOMATED_SNAPSHOT = 'REDSHIFT_COPY_AUTOMATED_SNAPSHOT'
    REDSHIFT_CREATE_SNAPSHOT = 'REDSHIFT_CREATE_SNAPSHOT'

    DEFAULTS = {
        'shelvery_keep_daily_backups': 14,
        'shelvery_keep_weekly_backups': 8,
        'shelvery_keep_monthly_backups': 12,
        'shelvery_keep_yearly_backups': 10,
        'shelvery_custom_retention_types': None,
        'shelvery_current_retention_type': None,
        'shelvery_wait_snapshot_timeout': 1200,
        'shelvery_lambda_max_wait_iterations': 5,
        'shelvery_dr_regions': None,
        'shelvery_rds_backup_mode': RDS_COPY_AUTOMATED_SNAPSHOT,
        'shelvery_source_aws_account_ids': None,
        'shelvery_share_aws_account_ids': None,
        'shelvery_redshift_backup_mode': REDSHIFT_COPY_AUTOMATED_SNAPSHOT,
        'shelvery_select_entity': None,
        'shelvery_bucket_name_template': 'shelvery.data.{account_id}-{region}.base2tools',
        'boto3_retries': 10,
        'role_arn': None,
        'role_external_id': None,
        'shelvery_copy_resource_tags': True,
        'shelvery_exluded_resource_tag_keys': None,
        'shelvery_sqs_queue_url': None,
        'shelvery_sqs_queue_wait_period': 0,
        'shelvery_ignore_invalid_resource_state': False
    }

    @classmethod
    def get_conf_value(cls, key: str, resource_tags=None, lambda_payload=None):
        # priority 3 are resource tags
        if resource_tags is not None:
            tag_key = f"shelvery:config:{key}"
            if tag_key in resource_tags:
                return resource_tags[tag_key]

        # priority 2 is lambda payload
        if (lambda_payload is not None) and ('config' in lambda_payload) and (key in lambda_payload['config']):
            return lambda_payload['config'][key]

        # priority 1 are environment variables
        if key in os.environ:
            return os.environ[key]

        # priority 0 are defaults
        if key in cls.DEFAULTS:
            return cls.DEFAULTS[key]

    @classmethod
    def is_lambda_runtime(cls, engine) -> bool:
        return engine.aws_request_id != 0 and engine.lambda_payload is not None

    @classmethod
    def is_offload_queueing(cls, engine) -> bool:
        return cls.get_sqs_queue_url(engine) is not None

    @classmethod
    def get_keep_daily(cls, resource_tags=None, engine=None):
        return int(cls.get_conf_value('shelvery_keep_daily_backups', resource_tags, engine.lambda_payload))

    @classmethod
    def get_keep_weekly(cls, resource_tags=None, engine=None):
        return int(cls.get_conf_value('shelvery_keep_weekly_backups', resource_tags, engine.lambda_payload))

    @classmethod
    def get_keep_monthly(cls, resource_tags=None, engine=None):
        return int(cls.get_conf_value('shelvery_keep_monthly_backups', resource_tags, engine.lambda_payload))

    @classmethod
    def get_keep_yearly(cls, resource_tags=None, engine=None):
        return int(cls.get_conf_value('shelvery_keep_yearly_backups', resource_tags, engine.lambda_payload))

    @classmethod
    def get_custom_retention_types(cls, engine=None):
        custom_retention = cls.get_conf_value('shelvery_custom_retention_types', None, engine.lambda_payload)
        if custom_retention is None or custom_retention.strip() == '':
            return {}

        retentions = custom_retention.split(',')
        rval = {}
        for retention in retentions:
            parts = retention.split(':')
            if len(parts) == 2:
                rval[parts[0]] = int(parts[1])
        return rval

    @classmethod
    def get_current_retention_type(cls, engine=None):
        current_retention_type = cls.get_conf_value('shelvery_current_retention_type', None, engine.lambda_payload)
        if current_retention_type is None or current_retention_type.strip() == '':
            return None
        return current_retention_type

    @classmethod
    def get_envvalue(cls, key: str, default_value):
        return os.environ[key] if key in os.environ else default_value

    @classmethod
    def get_tag_prefix(cls):
        return cls.get_envvalue('shelvery_tag_prefix', 'shelvery')

    @classmethod
    def get_dr_regions(cls, resource_tags, engine):
        regions = cls.get_conf_value('shelvery_dr_regions', resource_tags, engine.lambda_payload)
        return [] if regions is None else regions.split(',')

    @classmethod
    def is_started_internally(cls, engine) -> bool:
        # 1. running in lambda environment
        # 2. payload has 'is_stated_internally' key
        # 3. payload 'is_started_internally' key is set to True
        return cls.is_lambda_runtime(engine) \
               and 'is_started_internally' in engine.lambda_payload \
               and engine.lambda_payload['is_started_internally']

    @classmethod
    def get_wait_backup_timeout(cls, shelvery):
        if cls.is_lambda_runtime(shelvery):
            return (shelvery.lambda_context.get_remaining_time_in_millis() / 1000) - 20
        else:
            return int(cls.get_conf_value('shelvery_wait_snapshot_timeout', None, shelvery.lambda_payload))

    @classmethod
    def get_max_lambda_wait_iterations(cls):
        return int(cls.get_envvalue('shelvery_lambda_max_wait_iterations', '5'))

    @classmethod
    def get_share_with_accounts(cls, shelvery):
        # collect account from env vars
        accounts = cls.get_conf_value('shelvery_share_aws_account_ids', None, shelvery.lambda_payload)

        if accounts is not None and accounts.strip() == "":
            return []

        # by default it is empty list
        accounts = accounts.split(',') if accounts is not None else []

        # validate account format
        rval = []
        for acc in accounts:
            if re.match('^[0-9]{12}$', acc) is None:
                shelvery.logger.warn(f"Account id {acc} is not 12-digit number, skipping for share")
            else:
                rval.append(acc)
                shelvery.logger.info(f"Collected account {acc} to share backups with")

        return rval

    @classmethod
    def get_source_backup_accounts(cls, shelvery):
        # collect account from env vars
        accounts = cls.get_conf_value('shelvery_source_aws_account_ids', None, shelvery.lambda_payload)

        if accounts is not None and accounts.strip() == "":
            return []

        # by default it is empty list
        accounts = accounts.split(',') if accounts is not None else []

        # validate account format
        rval = []
        for acc in accounts:
            if re.match('^[0-9]{12}$', acc) is None:
                shelvery.logger.warn(f"Account id {acc} is not 12-digit number, skipping for share")
            else:
                rval.append(acc)
                shelvery.logger.info(f"Collected account {acc} to share backups with")

        return rval

    @classmethod
    def get_rds_mode(cls, resource_tags, engine):
        return cls.get_conf_value('shelvery_rds_backup_mode', resource_tags, engine.lambda_payload)

    @classmethod
    def get_redshift_mode(cls, resource_tags, engine):
        return cls.get_conf_value('shelvery_redshift_backup_mode', resource_tags, engine.lambda_payload)

    @classmethod
    def get_shelvery_select_entity(cls, engine):
        val = cls.get_conf_value('shelvery_select_entity', None, engine.lambda_payload)
        if val == '':
            return None
        return val


    @classmethod
    def get_sns_topic(cls, engine):
        return cls.get_conf_value('shelvery_sns_topic', None, engine.lambda_payload)

    @classmethod
    def boto3_retry_times(cls):
        return cls.get_conf_value('boto3_retries', None, None)

    @classmethod
    def get_error_sns_topic(cls, engine):
        topic = cls.get_conf_value('shelvery_error_sns_topic', None, engine.lambda_payload)
        if topic is None:
            topic = cls.get_conf_value('shelvery_sns_topic', None, engine.lambda_payload)
        return topic

    @classmethod
    def get_role_arn(cls, engine):
        return cls.get_conf_value('role_arn', None, engine.lambda_payload)

    @classmethod
    def get_role_external_id(cls, engine):
        return cls.get_conf_value('role_external_id', None, engine.lambda_payload)

    @classmethod
    def get_bucket_name_template(cls, engine):
        return cls.get_conf_value('shelvery_bucket_name_template', None, engine.lambda_payload)

    @classmethod
    def copy_resource_tags(cls, engine) -> bool:
        copy_tags = cls.get_conf_value('shelvery_copy_resource_tags', None, engine.lambda_payload)
        if copy_tags or copy_tags.lower() == 'true' or copy_tags == 0:
            return True
        else:
            return False

    @classmethod
    def ignore_invalid_resource_state(cls, engine) -> bool:
        ignore_state = cls.get_conf_value('shelvery_ignore_invalid_resource_state', None, engine.lambda_payload)
        if ignore_state or ignore_state.lower() == 'true' or ignore_state == 0:
            return True
        else:
            return False

    @classmethod
    def get_exluded_resource_tag_keys(cls, engine):
        # Exluding the tag_pefix as sthey are not necessary
        # and aws tags as aws is a tag reserved namespace
        keys = [cls.get_tag_prefix(),'aws:']
        exclude = cls.get_conf_value('shelvery_exluded_resource_tag_keys', None, engine.lambda_payload)
        if exclude is not None:
            keys += exclude.split(',')
        return keys

    @classmethod
    def get_sqs_queue_url(cls, engine):
        return cls.get_conf_value('shelvery_sqs_queue_url', None, engine.lambda_payload)

    @classmethod
    def get_sqs_queue_wait_period(cls, engine):
        return cls.get_conf_value('shelvery_sqs_queue_wait_period', None, engine.lambda_payload)
