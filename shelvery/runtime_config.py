import os


class RuntimeConfig:
    """Helper to read runtime and other values
    
       Valid environment variables are
       shelvery_keep_daily_backups - daily backups to keep, defaults to 14 days
       shelvery_keep_weekly_backups - daily backups to keep, defaults to 8 weeks
       shelvery_keep_monthly_backups - daily backups to keep, defaults to 12 months
       shelvery_keep_yearly_backups - daily backups to keep, defaults to 10 years
       
       shelvery_dr_region - disaster recovery region, empty (disabled) by default
       
       shelvery_keep_daily_backups_dr - daily backups to keep in disaster recover region
       shelvery_keep_weekly_backups_dr - daily backups to keep in disaster recover region
       shelvery_keep_monthly_backups_dr - daily backups to keep in disaster recover region
       shelvery_keep_yearly_backups_dr - daily backups to keep in disaster recover region
    """
    
    
    DEFAULT_KEEP_DAILY = 14
    DEFAULT_KEEP_WEEKLY = 8
    DEFAULT_KEEP_MONTHLY = 12
    DEFAULT_KEEP_YEARLY = 10
    
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
        return cls.get_envvalue('shelvery_tag_prefix', 'base2:shelvery')
    
    @classmethod
    def get_drregion(cls):
        return cls.get_envvalue('shelvery_dr_region', None)
    
    @classmethod
    def get_dr_enabled(cls):
        return cls.get_drregion() is not None
