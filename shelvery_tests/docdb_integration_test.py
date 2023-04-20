from abc import abstractmethod
import sys
import unittest
import pytest
import os
import boto3
from botocore.exceptions import WaiterError
from shelvery.engine import ShelveryEngine
from shelvery.runtime_config import RuntimeConfig
from shelvery_tests.resources import DOCDB_RESOURCE_NAME
from shelvery_tests.conftest import destination_account

from shelvery_tests.test_functions import setup, compare_backups

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.documentdb_backup import ShelveryDocumentDbBackup
from shelvery.aws_helper import AwsHelper

print(f"Python lib path:\n{sys.path}")
class TestResourceClass():
    
    def __init__(self):
        self.resource_name = None
        self.backups_engine = None
        self.client = None
        
    @abstractmethod
    def add_backup_tags(self):
        pass
    
class DocDBTestClass(TestResourceClass):
    
    def __init__(self):
        self.resource_name = DOCDB_RESOURCE_NAME
        self.backups_engine = ShelveryDocumentDbBackup()
        self.client = AwsHelper.boto3_client('docdb', region_name='ap-southeast-2')
        self.ARN = f"arn:aws:rds:{os.environ['AWS_DEFAULT_REGION']}:{AwsHelper.local_account_id()}:cluster:{self.resource_name}"

    def add_backup_tags(self):
        self.client.add_tags_to_resource(
            ResourceName=self.ARN,
            Tags=[{
                    'Key': f"{RuntimeConfig.get_tag_prefix()}:{ShelveryEngine.BACKUP_RESOURCE_TAG}",
                    'Value': 'true'
                    }, 
                    {'Key': 'Name', 
                    'Value': self.resource_name
                    }
                ]
        )
                
    def wait_for_resource(self):
        #TODO Check if this works, else go back to rds waiter for docdb cluster...
        try:
            self.client.get_waiter('db_cluster_available').wait(
                DBClusterIdentifier=self.resource_name,
                WaiterConfig={
                    'Delay': 30,
                    'MaxAttempts': 50
                }
            )
        except WaiterError as error:
            print("Waiting for Doc DB Cluster Failed")
            print(error)
            raise error

######## Test Case
class ShelveryDocDBIntegrationTestCase(unittest.TestCase):
    """Shelvery DocDB Backups Integration shelvery tests"""
    
    def id(self):
        return str(self.__class__)

    def setUp(self):
        # Complete initial setup
        setup(self, service_name='docdb')

        # Instantiate resource test class
        test_resource_class = DocDBTestClass()

        # Wait till DocDB Cluster is in an available state
        test_resource_class.wait_for_resource()

        # Add tags to indicate backup
        test_resource_class.add_backup_tags()

    @pytest.mark.source
    def test_CleanupDocDbBackup(self):
        print(f"Doc DB - Running cleanup test")
        
        # Create test resource class
        test_resource_class = DocDBTestClass()
        backups_engine = test_resource_class.backups_engine
        client = boto3.client('docdb')# DocDBTestClass().client()
        
        # Create backups
        backups =  backups_engine.create_backups() 
        
        # Clean backups
        backups_engine.clean_backups()
        
        # Retrieve remaining backups 
        snapshots = [
            snapshot
            for backup in backups
            for snapshot in client.describe_db_cluster_snapshots(
                DBClusterIdentifier=test_resource_class.resource_name,
                DBClusterSnapshotIdentifier=backup.backup_id
            )["DBClusterSnapshots"]
        ]
        
        print(f"Snapshots: {snapshots}")
        
        self.assertTrue(len(snapshots) == 0)

    @pytest.mark.source
    def test_CreateDocDbBackup(self):

        print(f"Doc DB - Running backup test")

       # Create test resource class
        test_resource_class = DocDBTestClass()
        backups_engine = test_resource_class.backups_engine
        
        # Create backups
        backups =  backups_engine.create_backups() 
        
        print("Created Doc DB Cluster backups")

        valid = False
        
        for backup in backups:
            valid = compare_backups(self=self,
                           backup=backup,
                           backup_engine=backups_engine
                           )
            self.assertTrue(valid)

    @pytest.mark.source
    @pytest.mark.share
    def test_ShareDocDbBackup(self):
        print(f"Doc DB - Running share backup test")
        
        # Create test resource class
        test_resource_class = DocDBTestClass()
        backups_engine = test_resource_class.backups_engine
        client = DocDBTestClass().client()
        
        print("Creating Shared Backups")
        backups = backups_engine.create_backups()
        print("Shared backups created")
 
        for backup in backups:
            snapshot_id = backup.backup_id
            print(f"Testing if snapshot {snapshot_id} is shared with {self.share_with_id}")
            
            # Retrieve snapshots
            snapshots = [
                snapshot
                for backup in backups
                for snapshot in client.describe_db_cluster_snapshots(
                    DBClusterIdentifier=test_resource_class.resource_name,
                    DBClusterSnapshotIdentifier=backup.backup_id
                )["DBClusterSnapshots"]
            ]

            print(f"Snapshots: {snapshots}")
            
            # Get attributes of snapshot
            attributes = client.describe_db_cluster_snapshot_attributes(
                DBClusterSnapshotIdentifier=snapshot_id
            )['DBClusterSnapshotAttributesResult']['DBClusterSnapshotAttributes']
            
            # Validate Restore attribute exists indicating restoreable snapshot
            restore_attribute = [attr for attr in attributes if attr['AttributeName'] == 'restore'][0]['AttributeValues']

            print("Attributes: " + str(restore_attribute))

            #Assert Snapshot exist
            self.assertTrue(len(snapshots['DBClusterSnapshots']) == 1)

            #Assert that snapshot is shared with dest account
            self.assertTrue(destination_account in restore_attribute)
            
    def tearDown(self):
        print("doc db - tear down doc db snapshot")
        docdbclient = AwsHelper.boto3_client('docdb', region_name='ap-southeast-2')
        for snapid in self.created_snapshots:
            print(f"Deleting snapshot {snapid}")
            try:
                docdbclient.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snapid)
            except Exception as e:
                print(f"Failed to delete {snapid}:{str(e)}")

        print("docdb - snapshot deleted, instance deleting")

if __name__ == '__main__':
    unittest.main()
