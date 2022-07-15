import sys
import traceback
from turtle import back
import unittest
import pytest
import yaml

import boto3
import os
import time
import botocore
from datetime import datetime

from shelvery_tests.test_functions import clusterCleanupBackups, clusterShareBackups, compareBackups, initCleanup, initCreateBackups, addBackupTags, initShareBackups, initSetup

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.rds_cluster_backup import ShelveryRDSClusterBackup
from shelvery.engine import ShelveryEngine
from shelvery.engine import S3_DATA_PREFIX
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.aws_helper import AwsHelper


print(f"Python lib path:\n{sys.path}")


class ShelveryRDSClusterIntegrationTestCase(unittest.TestCase):
    """Shelvery RDS Cluster Backups Integration shelvery tests"""

    def id(self):
        return str(self.__class__)


    def setUp(self):
        self.created_snapshots = []
        self.regional_snapshots = {
            'ap-southeast-1': [],
            'ap-southeast-2': []
        }

       # Complete initial setup and create service client
        initSetup(self,'rds')
        rdsclient = AwsHelper.boto3_client('docdb', region_name='ap-southeast-2')


        #Get cluster name
        clustername = f"arn:aws:rds:{os.environ['AWS_DEFAULT_REGION']}:{self.id['Account']}:cluster:shelvery-test-rds-cluster"

        #Add tags to indicate backup
        addBackupTags(rdsclient,
                      clustername,
                      "shelvery-test-rds-cluster")

        self.share_with_id = 186991632813

    @pytest.mark.source
    def test_Cleanup(self):
        print(f"rds cluster - Running cleanup test")
        rdscluster_backups_engine = ShelveryRDSClusterBackup()
        backups = initCleanup(rdscluster_backups_engine)
        rdscluster_client = AwsHelper.boto3_client('rds')

        valid = False
        for backup in backups:
            valid = clusterCleanupBackups(self=self,
                                  backup=backup,
                                  backup_engine=rdscluster_backups_engine,
                                  resource_client=rdscluster_client)
        
        self.assertTrue(valid)

    @pytest.mark.source
    def test_CreateRdsClusterBackup(self):

        print(f"rds cluster - Running backup test")

        rds_cluster_backup_engine = ShelveryRDSClusterBackup()
        print(f"rds cluster - Shelvery backup initialised")
        
        backups = initCreateBackups(rds_cluster_backup_engine)
        print("Created RDS Cluster backups")

        valid = False

        # validate there is
        for backup in backups:
            valid = compareBackups(self=self,
                           backup=backup,
                           backup_engine=rds_cluster_backup_engine
                           )
        self.assertTrue(valid)

    @pytest.mark.source
    @pytest.mark.share
    def test_ShareRdsClusterBackup(self):

        print(f"rds cluster - Running share backup test")
        rds_cluster_backup_engine = ShelveryRDSClusterBackup()

        print("Creating shared backups")
        backups = initShareBackups(rds_cluster_backup_engine, str(self.share_with_id))

        print("Shared backups created")
        
        #Create source/dest sessions
        source_session = boto3.Session(profile_name="test-dev")
        source_client = source_session.client('rds')

        dest_session = boto3.Session(profile_name="test-ops")
        dest_client = dest_session.client('rds')

        valid = False
        # validate there is
        for backup in backups:
            valid = clusterShareBackups(self=self,
                                       backup=backup,
                                       source_client=source_client,
                                       dest_client=dest_client)

        self.assertTrue(valid)

    def tearDown(self):
        print("rds cluster - tear down rds cluster snapshot")
        rdsclient = AwsHelper.boto3_client('rds', region_name='ap-southeast-2')
        for snapid in self.created_snapshots:
            print(f"Deleting snapshot {snapid}")
            try:
                rdsclient.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snapid)
            except Exception as e:
                print(f"Failed to delete {snapid}:{str(e)}")

        print("rds - snapshot deleted, instance deleting")



if __name__ == '__main__':
    unittest.main()
