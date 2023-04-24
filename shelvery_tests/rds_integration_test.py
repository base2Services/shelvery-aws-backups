import sys
import unittest
import pytest
import os
from botocore.exceptions import WaiterError
from shelvery.engine import ShelveryEngine
from shelvery.runtime_config import RuntimeConfig
from shelvery_tests.test_functions import setup_source, compare_backups
from shelvery.rds_backup import ShelveryRDSBackup
from shelvery.aws_helper import AwsHelper
from shelvery_tests.resources import RDS_INSTANCE_RESOURCE_NAME, ResourceClass

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

print(f"Python lib path:\n{sys.path}")

class RDSInstanceTestClass(ResourceClass):
    
    def __init__(self):
        self.resource_name = RDS_INSTANCE_RESOURCE_NAME
        self.backups_engine = ShelveryRDSBackup()
        self.client = AwsHelper.boto3_client('rds', region_name='ap-southeast-2')
        self.ARN = f"arn:aws:rds:{os.environ['AWS_DEFAULT_REGION']}:{AwsHelper.local_account_id()}:db:{self.resource_name}"

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
        waiter = AwsHelper.boto3_client('rds', region_name='ap-southeast-2').get_waiter('db_instance_available')
        try:
            waiter.wait(
                DBInstanceIdentifier=self.resource_name,
                WaiterConfig={
                    'Delay': 30,
                    'MaxAttempts': 50
                }
            )
        except WaiterError as error:
            print("Waiting for RDS Instance Failed")
            print(error)
            raise error

######## Test Case
class ShelveryRDSIntegrationTestCase(unittest.TestCase):
    """Shelvery RDS Instance Backups Integration shelvery tests"""

    def id(self):
        return str(self.__class__)

    def setUp(self):
        # Complete initial setup
        self.created_snapshots = []
        setup_source(self)
        # Instantiate resource test class
        rds_instance_test_class = RDSInstanceTestClass()
        # Wait till RDS Instance is in an available state
        rds_instance_test_class.wait_for_resource()
        # Add tags to indicate backup
        rds_instance_test_class.add_backup_tags()

    @pytest.mark.source
    def test_CleanupRdsInstanceBackup(self):
        print(f"RDS Instance - Running cleanup test")
        # Create test resource class
        rds_instance_test_class = RDSInstanceTestClass()
        backups_engine = rds_instance_test_class.backups_engine
        client = rds_instance_test_class.client
        # Create backups
        backups =  backups_engine.create_backups() 
        # Clean backups
        backups_engine.clean_backups()
        # Retrieve remaining backups 
        snapshots = [
            snapshot
            for backup in backups
            for snapshot in client.describe_db_snapshots(
                DBInstanceIdentifier=rds_instance_test_class.resource_name,
                DBSnapshotIdentifier=backup.backup_id
            )["DBSnapshots"]
        ]
        print(f"Snapshots: {snapshots}")
        
        self.assertTrue(len(snapshots) == 0)
        
    @pytest.mark.source
    def test_CreateRdsInstanceBackup(self):
        print("Running RDS Instance create backup test")
        # Instantiate test resource class
        rds_instance_test_class = RDSInstanceTestClass()
        backups_engine = rds_instance_test_class.backups_engine
        
        # Create backups
        backups = backups_engine.create_backups()
        print(f"Created {len(backups)} backups for RDS Instance")
        
        # Compare backups
        for backup in backups:
            valid = compare_backups(self=self, backup=backup, backup_engine=backups_engine)
            
            # Clean backups
            print(f"Cleaning up RDS Instance Backups")
            backups_engine.clean_backups()
            
            # Validate backups
            self.assertTrue(valid, f"Backup {backup} is not valid")
            
        self.assertEqual(len(backups), 1, f"Expected 1 backup, but found {len(backups)}")
            
    @pytest.mark.source
    @pytest.mark.share
    def test_shareRdsInstanceBackup(self):
        
        print("Running RDS Instance share backup test")

        # Instantiate test resource class
        rds_instance_test_class = RDSInstanceTestClass()
        backups_engine = rds_instance_test_class.backups_engine
        client = rds_instance_test_class.client

        print("Creating shared backups")
        backups = backups_engine.create_backups()
        print(f"{len(backups)} shared backups created")

        for backup in backups:
            snapshot_id = backup.backup_id
            print(f"Checking if snapshot {snapshot_id} is shared with {self.share_with_id}")

            # Retrieve remaining backups 
            snapshots = [
                snapshot
                for backup in backups
                for snapshot in client.describe_db_snapshots(
                    DBInstanceIdentifier=rds_instance_test_class.resource_name,
                    DBSnapshotIdentifier=backup.backup_id
                )["DBSnapshots"]
            ]

            # Get attributes of snapshot
            attributes = client.describe_db_snapshot_attributes(
                DBSnapshotIdentifier=snapshot_id
            )['DBSnapshotAttributesResult']['DBSnapshotAttributes']
            
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
