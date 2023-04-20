from abc import abstractmethod

DOCDB_RESOURCE_NAME='shelvery-test-docdb'
RDS_INSTANCE_RESOURCE_NAME='shelvery-test-rds'

class ResourceClass():
    
    def __init__(self):
        self.resource_name = None
        self.backups_engine = None
        self.client = None
        
    @abstractmethod
    def add_backup_tags(self):
        pass