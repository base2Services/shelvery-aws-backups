import sys
import unittest
import pytest
import os
from botocore.exceptions import WaiterError
from shelvery.engine import ShelveryEngine
from shelvery.runtime_config import RuntimeConfig
from shelvery_tests.resources import DOCDB_RESOURCE_NAME, ResourceClass
from shelvery_tests.test_functions import setup_source, compare_backups
from shelvery.documentdb_backup import ShelveryDocumentDbBackup
from shelvery.aws_helper import AwsHelper

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")



print(f"Python lib path:\n{sys.path}")

class DocDBTestClass(ResourceClass):
    
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
        waiter = AwsHelper.boto3_client('rds', region_name='ap-southeast-2').get_waiter('db_cluster_available')
        try:
            waiter.wait(
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
        self.created_snapshots = []
        setup_source(self)
        # Instantiate resource test class
        docdb_test_class = DocDBTestClass()
        # Wait till DocDB Cluster is in an available state
        docdb_test_class.wait_for_resource()
        # Add tags to indicate backup
        docdb_test_class.add_backup_tags()

    @pytest.mark.source
    def test_CleanupDocDbBackup(self):
        print(f"Doc DB - Running cleanup test")
        # Create test resource class
        docdb_test_class = DocDBTestClass()
        backups_engine = docdb_test_class.backups_engine
        client = docdb_test_class.client
        # Create backups
        backups =  backups_engine.create_backups() 
        # Clean backups
        backups_engine.clean_backups()
        # Retrieve remaining backups 
        snapshots = [
            snapshot
            for backup in backups
            for snapshot in client.describe_db_cluster_snapshots(
                DBClusterIdentifier=docdb_test_class.resource_name,
                DBClusterSnapshotIdentifier=backup.backup_id
            )["DBClusterSnapshots"]
        ]
        print(f"Snapshots: {snapshots}")
        
        self.assertTrue(len(snapshots) == 0)

    @pytest.mark.source
    def test_CreateDocDbBackup(self):
        print("Running DocDB create backup test")
        # Instantiate test resource class
        docdb_test_class = DocDBTestClass()
        backups_engine = docdb_test_class.backups_engine
        
        # Create backups
        backups = backups_engine.create_backups()
        print(f"Created {len(backups)} backups for Doc DB cluster")
        
        # Compare backups
        for backup in backups:
            valid = compare_backups(self=self, backup=backup, backup_engine=backups_engine)
            
            # Clean backups
            print(f"Cleaning up DocDB Backups")
            backups_engine.clean_backups()
            
            #Validate backup
            self.assertTrue(valid, f"Backup {backup} is not valid")
            
        self.assertEqual(len(backups), 1, f"Expected 1 backup, but found {len(backups)}")

    @pytest.mark.source
    @pytest.mark.share
    def test_ShareDocDbBackup(self):
        print("Running Doc DB share backup test")

        # Instantiate test resource class
        docdb_test_class = DocDBTestClass()
        backups_engine = docdb_test_class.backups_engine
        client = docdb_test_class.client

        print("Creating shared backups")
        backups = backups_engine.create_backups()
        print(f"{len(backups)} shared backups created")

        for backup in backups:
            snapshot_id = backup.backup_id
            print(f"Checking if snapshot {snapshot_id} is shared with {self.share_with_id}")

            # Retrieve snapshots
            snapshots = client.describe_db_cluster_snapshots(
                DBClusterIdentifier=docdb_test_class.resource_name,
                DBClusterSnapshotIdentifier=backup.backup_id
            )["DBClusterSnapshots"]

            # Get attributes of snapshot
            attributes = client.describe_db_cluster_snapshot_attributes(
                DBClusterSnapshotIdentifier=snapshot_id
            )['DBClusterSnapshotAttributesResult']['DBClusterSnapshotAttributes']
            
            # Check if snapshot is shared with destination account
            shared_with_destination = any(
                attr['AttributeName'] == 'restore' and self.share_with_id in attr['AttributeValues']
                for attr in attributes
            )
            
            # Assertions
            self.assertEqual(len(snapshots), 1, f"Expected 1 snapshot, but found {len(snapshots)}")
            self.assertTrue(shared_with_destination, f"Snapshot {snapshot_id} is not shared with {self.share_with_id}")
        
if __name__ == '__main__':
    unittest.main()
