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
from shelvery.rds_cluster_backup import ShelveryRDSClusterBackup

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
from shelvery_tests.cleanup_functions import cleanRdsClusterSnapshots

#Need to add 'source acc' to env 
#Call create_data_bucket
#How to cleanup source account after running in dest?

class ShelveryRDSClusterPullTestCase(unittest.TestCase):
    
    @pytest.mark.destination
    def test_PullRdsClusterBackup(self):
        
        os.environ['SHELVERY_MONO_THREAD'] = '1'
        cleanRdsClusterSnapshots()

        source_aws_id = source_account
        os.environ["shelvery_source_aws_account_ids"] = str(source_aws_id)

        print(f"rds cluster - Running pull shared backups test")
    
        rds_cluster_client = AwsHelper.boto3_client('rds', region_name='ap-southeast-2')
        rds_cluster_backup_engine = ShelveryRDSClusterBackup()

        
        print("Pulling shared backups")
        rds_cluster_backup_engine.pull_shared_backups()

        #Get post-pull snapshot count
        pulled_snapshot = rds_cluster_client.describe_db_cluster_snapshots(
            DBClusterIdentifier='shelvery-test-rds-cluster',
            SnapshotType='Manual'
        )
       
        print("PULLED:" + str(pulled_snapshot))

        self.assertTrue(len(pulled_snapshot['DBClusterSnapshots']) == 1)

    @pytest.mark.cleanup
    def test_cleanup(self):
       cleanRdsClusterSnapshots()


        


    