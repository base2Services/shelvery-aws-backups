from abc import abstractmethod

DOCDB_RESOURCE_NAME='shelvery-test-docdb'
RDS_INSTANCE_RESOURCE_NAME='shelvery-test-rds'
RDS_CLUSTER_RESOURCE_NAME='shelvery-test-rds-cluster'
EC2_AMI_INSTANCE_RESOURCE_NAME='shelvery-test-ec2'
EBS_INSTANCE_RESOURCE_NAME='shelvery-test-ebs'
class ResourceClass():
    
    def __init__(self):
        self.resource_name = None
        self.backups_engine = None
        self.client = None
        
    @abstractmethod
    def add_backup_tags(self):
        pass
    
    @abstractmethod
    def wait_for_resource(self):
        pass