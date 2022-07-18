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
from shelvery.rds_backup import ShelveryRDSBackup

from shelvery_tests.cleanup_functions import cleanRdsSnapshots

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
from shelvery_tests.conftest import source_account

#Need to add 'source acc' to env 
#Call create_data_bucket
#How to cleanup source account after running in dest?

class ShelveryRDSPullTestCase(unittest.TestCase):
    
    @pytest.mark.destination
    def test_PullRdsBackup(self):

        cleanRdsSnapshots()

        source_aws_id = source_account
        os.environ["shelvery_source_aws_account_ids"] = str(source_aws_id)

        print(f"rds - Running pull shared backups test")
    
        rds_client = AwsHelper.boto3_client('rds', region_name='ap-southeast-2')
        rds_backup_engine = ShelveryRDSBackup()


        print("Pulling shared backups")
        rds_backup_engine.pull_shared_backups()

        #Get post-pull snapshot count
        pulled_snapshot = rds_client.describe_db_snapshots(
            DBInstanceIdentifier='shelvery-test-rds',
            SnapshotType='Manual'
        )

        print("PULLED:" + str(pulled_snapshot))
        self.assertTrue(len(pulled_snapshot['DBSnapshots']) == 1)



    @pytest.mark.cleanup
    def test_cleanup(self):
        cleanRdsSnapshots()




        


    