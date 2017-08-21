import re
import os


class RuntimeConfig:
    """
    Helper to read runtime and other values
    Valid environment variables are
    
    shelvery_keep_daily_backups - daily backups to keep, defaults to 14 days
    shelvery_keep_weekly_backups - daily backups to keep, defaults to 8 weeks
    shelvery_keep_monthly_backups - daily backups to keep, defaults to 12 months
    shelvery_keep_yearly_backups - daily backups to keep, defaults to 10 years
    
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
    """
    
    DEFAULT_KEEP_DAILY = 14
    DEFAULT_KEEP_WEEKLY = 8
    DEFAULT_KEEP_MONTHLY = 12
    DEFAULT_KEEP_YEARLY = 10

    RDS_COPY_AUTOMATED_SNAPSHOT = 'RDS_COPY_AUTOMATED_SNAPSHOT'
    RDS_CREATE_SNAPSHOT = 'RDS_CREATE_SNAPSHOT'
    
    @classmethod
    def is_lambda_runtime(cls, engine) -> bool:
        return engine.aws_request_id != 0 and engine.lambda_payload is not None
    
    @classmethod
    def get_keep_daily(cls, dr=False):
        return int(cls.get_envvalue(f"shelvery_keep_daily_backups{'_dr' if dr else ''}",
                                    cls.DEFAULT_KEEP_DAILY))
    
    @classmethod
    def get_keep_weekly(cls, dr=False):
        return int(cls.get_envvalue(f"shelvery_keep_weekly_backups{'_dr' if dr else ''}", cls.DEFAULT_KEEP_WEEKLY))
    
    @classmethod
    def get_keep_monthly(cls, dr=False):
        return int(cls.get_envvalue(f"shelvery_keep_monthly_backups{'_dr' if dr else ''}", cls.DEFAULT_KEEP_MONTHLY))
    
    @classmethod
    def get_keep_yearly(cls, dr=False):
        return int(cls.get_envvalue(f"shelvery_keep_yearly_backups{'_dr' if dr else ''}", cls.DEFAULT_KEEP_YEARLY))
    
    @classmethod
    def get_envvalue(cls, key: str, default_value):
        return os.environ[key] if key in os.environ else default_value
    
    @classmethod
    def get_tag_prefix(cls):
        return cls.get_envvalue('shelvery_tag_prefix', 'shelvery')
    
    @classmethod
    def get_dr_regions(cls):
        regions = cls.get_envvalue('shelvery_dr_regions', None)
        return [] if regions is None else regions.split(',')
    
    @classmethod
    def get_dr_enabled(cls):
        return cls.get_dr_regions() is not None
    
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
            return int(cls.get_envvalue('shelvery_wait_snapshot_timeout', '1200'))
    
    @classmethod
    def get_max_lambda_wait_iterations(cls):
        return int(cls.get_envvalue('shelvery_lambda_max_wait_iterations', '5'))
    
    @classmethod
    def get_share_with_accounts(cls, shelvery):
        # collect account from env vars
        accounts = cls.get_envvalue('shelvery_share_aws_account_ids', None)
        
        # by default it is empty list
        accounts = accounts.split(',') if accounts is not None else []
        
        # collect account from lambda payload
        if cls.is_lambda_runtime(shelvery) and 'share_aws_account_ids' in shelvery.lambda_payload:
            accounts = accounts + shelvery.lambda_payload['share_aws_account_ids']
        
        # validate account format
        for acc in accounts:
            if re.match('^[0-9]{12}$', acc) is None:
                shelvery.logger.warn(f"Account id {acc} is not 12-digit number, skipping for share")
            else:
                shelvery.logger.info(f"Collected account {acc} to share backups with")
        
        return accounts
    
    @classmethod
    def get_rds_mode(cls):
        rds_backup_mode = cls.get_envvalue('rds_backup_mode', cls.RDS_COPY_AUTOMATED_SNAPSHOT)
        return rds_backup_mode
