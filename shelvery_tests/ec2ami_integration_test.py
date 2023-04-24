import sys
import unittest
import pytest
import os
from botocore.exceptions import WaiterError
from shelvery.engine import ShelveryEngine
from shelvery.runtime_config import RuntimeConfig
from shelvery_tests.test_functions import setup_source, compare_backups
from shelvery.ec2ami_backup import ShelveryEC2AMIBackup
from shelvery.aws_helper import AwsHelper
from shelvery_tests.resources import EC2_AMI_INSTANCE_RESOURCE_NAME, ResourceClass


pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

print(f"Python lib path:\n{sys.path}")

import boto3
class EC2AmiTestClass(ResourceClass):
    
    def __init__(self):
        self.resource_name = EC2_AMI_INSTANCE_RESOURCE_NAME
        self.backups_engine = ShelveryEC2AMIBackup()
        self.client = AwsHelper.boto3_client('ec2', region_name='ap-southeast-2')
        self.resource_id = self.get_instance_id()

    def add_backup_tags(self):
        self.client.create_tags(
            Resources=[self.resource_id],
            Tags=[{
                    'Key': f"{RuntimeConfig.get_tag_prefix()}:{ShelveryEngine.BACKUP_RESOURCE_TAG}",
                    'Value': 'true'
                    }, 
                    {'Key': 'Name', 
                   'Value': self.resource_name
                    }]
        )
                
    def get_instance_id(self):
        # Find EC2 instance
        search_filter = [
            {'Name': 'tag:Name', 'Values': [EC2_AMI_INSTANCE_RESOURCE_NAME]},
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]

        # Get EC2 instance
        ec2_instance = self.client.describe_instances(Filters=search_filter)

        # Get instance ID
        try:
            return ec2_instance['Reservations'][0]['Instances'][0]['InstanceId']
        except (IndexError, KeyError):
            print("No instance found matching the given criteria.")    
            return ""        
            
    def wait_for_resource(self):
        waiter = AwsHelper.boto3_client('ec2', region_name='ap-southeast-2').get_waiter('instance_running')
        try:
            waiter.wait(
                InstanceIds=[self.resource_id],
                WaiterConfig={
                    'Delay': 30,
                    'MaxAttempts': 50
                }
            )
        except WaiterError as error:
            print("Waiting for EC2 Instance Failed")
            print(error)
            raise error

class ShelveryEC2AmiIntegrationTestCase(unittest.TestCase):
    """Shelvery EC2 AMI Backups Integration shelvery tests"""

    def id(self):
        return str(self.__class__)

    def setUp(self):
        # Complete initial setup
        self.created_snapshots = []
        self.regional_snapshots = []
        setup_source(self)
        # Instantiate resource test class
        ec2_ami_test_class = EC2AmiTestClass()
        # Wait till instance is in an available state
        ec2_ami_test_class.wait_for_resource()
        # Add tags to indicate backup
        ec2_ami_test_class.add_backup_tags()

    @pytest.mark.source
    def test_CleanupEC2AmiBackup(self):
        
        print(f"EC2 Ami - Running cleanup test")
        # Create test resource class
        ec2_ami_test_class = EC2AmiTestClass()
        backups_engine = ec2_ami_test_class.backups_engine
        client = ec2_ami_test_class.client
        # Create backups
        backups =  backups_engine.create_backups() 
        # Clean backups
        backups_engine.clean_backups()
        # Retrieve remaining backups 
        snapshots = [
            snapshot
            for backup in backups
            for snapshot in client.describe_snapshots(
                Filters = [{
                    'Name': 'tag:Name',
                    'Values': [backup.name]
                }]
            )['Snapshots']
        ]
        print(f"Snapshots: {snapshots}")
        
        self.assertTrue(len(snapshots) == 0)

    @pytest.mark.source
    def test_CreateEc2AmiBackup(self):
        print("Running EC2 AMI create backup test")
        # Create test resource class
        ec2_ami_test_class = EC2AmiTestClass()
        backups_engine = ec2_ami_test_class.backups_engine
        
        # Create backups
        backups = backups_engine.create_backups()
        print(f"Created {len(backups)} backups for EC2 Instance")
        
        # Compare backups
        for backup in backups:
            valid = compare_backups(self=self, backup=backup, backup_engine=backups_engine)
            
            # Clean backups
            print(f"Cleaning up EC2 AMI Backups")
            backups_engine.clean_backups()
            
            #Validate backup
            self.assertTrue(valid, f"Backup {backup} is not valid")
            
        self.assertEqual(len(backups), 1, f"Expected 1 backup, but found {len(backups)}")
            
    @pytest.mark.source
    @pytest.mark.share
    def test_ShareEc2AmiBackup(self):
        print("Running EC2 AMI share backup test")
        # Instantiate test resource classs
        ec2_ami_test_class = EC2AmiTestClass()
        backups_engine = ec2_ami_test_class.backups_engine
        client = boto3.client('ec2')#ec2_ami_test_class.client

        print("Creating shared backups")
        backups = backups_engine.create_backups()
        print(f"{len(backups)} shared backups created")

        for backup in backups:
            snapshot_id = backup.backup_id
            print(f"Checking if snapshot {snapshot_id} is shared with {self.share_with_id}")

            # Retrieve snapshot
            snapshots = client.describe_snapshots(
                Filters = [{
                    'Name': 'tag:Name',
                    'Values': [backup.name]
                }]
            )['Snapshots']
            
            snapshot_id = snapshots[0]['SnapshotId']

            # retrieve the snapshot attributes
            response = client.describe_snapshot_attribute(
                SnapshotId=snapshot_id,
                Attribute='createVolumePermission'
            )

            # check if the snapshot is shared with the destination account
            shared_with_destination = any(
                perm['UserId'] == self.share_with_id for perm in response.get('CreateVolumePermissions', [])
            )
            
            # Assertions
            self.assertEqual(len(snapshots), 1, f"Expected 1 snapshot, but found {len(snapshots)}")
            self.assertTrue(shared_with_destination, f"Snapshot {snapshot_id} is not shared with {self.share_with_id}")


if __name__ == '__main__':
    unittest.main()
