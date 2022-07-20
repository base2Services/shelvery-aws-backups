import sys
import traceback
import unittest
import pytest
import yaml

import boto3
import os
import time
import botocore
from datetime import datetime

from shelvery_tests.test_functions import compareBackups, createBackupTags, ec2CleanupBackups, ec2ShareBackups, initCleanup, initCreateBackups, initSetup, initShareBackups

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.ec2ami_backup import ShelveryEC2AMIBackup
from shelvery.engine import ShelveryEngine
from shelvery.engine import S3_DATA_PREFIX
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.aws_helper import AwsHelper
from shelvery_tests.conftest import destination_account

print(f"Python lib path:\n{sys.path}")


## Add check for non-terminated ec2am? (because it takes ages to transition from terminated -> deleted)

class ShelveryEC2AmiIntegrationTestCase(unittest.TestCase):
    """Shelvery EC2 AMI Backups Integration shelvery tests"""

    def id(self):
        return str(self.__class__)

    def setUp(self):
        self.created_snapshots = []
        self.regional_snapshots = {
            'ap-southeast-1': [],
            'ap-southeast-2': []
        }
        os.environ['SHELVERY_MONO_THREAD'] = '1'

        # Create and configure RDS artefact
        initSetup(self,'ec2')
        ec2client = AwsHelper.boto3_client('ec2', region_name='ap-southeast-2')

        #Find ec2 instance
        search_filter = [{'Name':'tag:Name',
                          'Values': ['shelvery-test-ec2'],
                          'Name': 'instance-state-name',
                          'Values': ['running']
                        }]
                        
    
        #Get ec2 instance
        ec2_instance = ec2client.describe_instances(Filters = search_filter)

        #Get instance id, looks dodgy is there a better way?
        instance_id = ec2_instance['Reservations'][0]['Instances'][0]['InstanceId']
        print("INSTANCE ID: " + str(instance_id))

        createBackupTags(ec2client,[instance_id],"shelvery-test-ec2")

        self.share_with_id = destination_account

    @pytest.mark.source
    def test_Cleanup(self):
        print(f"ec2 ami - Running cleanup test")
        ec2_ami_backup_engine = ShelveryEC2AMIBackup()
        backups = initCleanup(ec2_ami_backup_engine)
        ec2_client = AwsHelper.boto3_client('ec2')

        valid = False
        for backup in backups:
            valid = ec2CleanupBackups(self=self,
                                 backup=backup,
                                 backup_engine=ec2_ami_backup_engine,
                                 service_client=ec2_client)
        
        self.assertTrue(valid)

    @pytest.mark.source
    def test_CreateEc2AmiBackup(self):
        print(f"ec2 ami - Running backup test")

        ec2_ami_backup_engine = ShelveryEC2AMIBackup()
        print(f"ec2 ami - Shelvery backup initialised")

        backups = initCreateBackups(ec2_ami_backup_engine)

        ec2_client = AwsHelper.boto3_client('ec2')

        valid = False
        # validate there is
        for backup in backups:
   
            #Get source snapshot
            source_snapshot = ec2_client.describe_snapshots( 
               Filters = [{
                   'Name': 'tag:Name',
                   'Values': [
                       backup.name
                   ]
               }]
            )  

            #Get snapshot id and add to created snapshot list for removal in teardown later
            dest_snapshot_id = source_snapshot['Snapshots'][0]['SnapshotId']
            self.created_snapshots.append(dest_snapshot_id)

            valid = compareBackups(self=self,
                           backup=backup,
                           backup_engine=ec2_ami_backup_engine
                          )


        self.assertTrue(valid)

    @pytest.mark.source
    @pytest.mark.share
    def test_ShareEc2AmiBackup(self):

        print(f"ec2 ami - Running share backup test")
        ec2_ami_backup_engine = ShelveryEC2AMIBackup()

        print("Creating shared backups")
        backups = initShareBackups(ec2_ami_backup_engine, str(self.share_with_id))

        print("Shared backups created")

        valid = False
        # validate there is
        for backup in backups:
            valid = ec2ShareBackups(self=self,
                               backup=backup,
                               )
        self.assertTrue(valid)

    def tearDown(self):
        ec2client = AwsHelper.boto3_client('ec2')
        # snapshot deletion surrounded with try/except in order
        # for cases when shelvery cleans / does not clean up behind itself
        time.sleep(20)
        for snapid in self.created_snapshots:
            print(f"Deleting snapshot {snapid}")
            try:
                snapshot = ec2client.describe_snapshots(
                    SnapshotIds = [snapid]
                )
                
                print(snapshot)

                tags = snapshot['Snapshots'][0]['Tags']

                print("TAGS")
                print(tags)

                ami_id = [tag['Value'] for tag in tags if tag['Key'] == 'shelvery:ami_id'][0]

                print("AMI")
                print(ami_id)

                ec2client.deregister_image(ImageId=ami_id)
                ec2client.delete_snapshot(SnapshotId=snapid)
            except Exception as e:
                print(f"Failed to delete {snapid}:{str(e)}")

        for region in self.regional_snapshots:
            ec2regional = AwsHelper.boto3_client('ec2', region_name=region)
            for snapid in self.regional_snapshots[region]:
                try:
                    ec2regional.delete_snapshot(SnapshotId=snapid)
                except Exception as e:
                    print(f"Failed to delete {snapid}:{str(e)}")



if __name__ == '__main__':
    unittest.main()
