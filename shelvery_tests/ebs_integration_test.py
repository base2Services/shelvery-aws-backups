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
from shelvery.ebs_backup import ShelveryEBSBackup

from shelvery_tests.test_functions import compareBackups, createBackupTags, ebsCleanupBackups, ec2ShareBackups, initCleanup, initCreateBackups, initSetup, initShareBackups

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.engine import ShelveryEngine
from shelvery.engine import S3_DATA_PREFIX
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.aws_helper import AwsHelper
from shelvery_tests.conftest import destination_account

print(f"Python lib path:\n{sys.path}")


class ShelveryEBSIntegrationTestCase(unittest.TestCase):
    """Shelvery EBS Backups Integration shelvery tests"""

    def id(self):
        return str(self.__class__)

    def setUp(self):
        self.created_snapshots = []
        self.regional_snapshots = {
            'ap-southeast-1': [],
            'ap-southeast-2': []
        }

        # Create and configure RDS artefact
        initSetup(self,'ec2')
        ec2client = AwsHelper.boto3_client('ec2', region_name='ap-southeast-2')

        #Find ec2 instance
        search_filter = [{'Name':'tag:Name',
                          'Values': ['shelvery-test-ebs']  
                        }]
    
        #Get ebs volume
        ebs_volume = ec2client.describe_volumes(Filters = search_filter)

        print(ebs_volume)

        #Get instance id, looks dodgy is there a better way?
        volume_id = ebs_volume['Volumes'][0]['VolumeId']

        createBackupTags(ec2client,[volume_id],"shelvery-test-ebs")

        self.share_with_id = destination_account
        
    @pytest.mark.source
    def test_Cleanup(self):
        print(f"ebs - Running cleanup test")
        ebs_backup_engine = ShelveryEBSBackup()
        backups = initCleanup(ebs_backup_engine)
        ec2_client = AwsHelper.boto3_client('ec2')

        valid = False
        for backup in backups:
            valid = ebsCleanupBackups(self=self,
                                 backup=backup,
                                 backup_engine=ebs_backup_engine,
                                 service_client=ec2_client)
        
        self.assertTrue(valid)

    @pytest.mark.source
    def test_CreateEbsBackup(self):
        print(f"ebs - Running backup test")

        ebs_backup_engine = ShelveryEBSBackup()
        print(f"ebs - Shelvery backup initialised")

        backups = initCreateBackups(ebs_backup_engine)

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
                           backup_engine=ebs_backup_engine
                          )

        self.assertTrue(valid)

    @pytest.mark.source
    @pytest.mark.share
    def test_ShareEbsBackup(self):

        print(f"ebs - Running share backup test")
        ebs_backup_engine = ShelveryEBSBackup()

        print("Creating shared backups")
        backups = initShareBackups(ebs_backup_engine, str(self.share_with_id))

        print("Shared backups created")

        #Create source/dest sessions
        source_session = boto3.Session(profile_name="test-dev")
        source_client = source_session.client('ec2')

        dest_session = boto3.Session(profile_name="test-ops")
        dest_client = dest_session.client('ec2')

        valid = False
        # validate there is
        for backup in backups:
            valid = ec2ShareBackups(self=self,
                               backup=backup,
                               source_client=source_client,
                               dest_client=dest_client
                               )
        self.assertTrue(valid)

    def tearDown(self):
        ec2client = AwsHelper.boto3_client('ec2')
        time.sleep(20)
        # snapshot deletion surrounded with try/except in order
        # for cases when shelvery cleans / does not clean up behind itself
        for snapid in self.created_snapshots:

            print(f"Deleting snapshot {snapid}")
            try:
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
