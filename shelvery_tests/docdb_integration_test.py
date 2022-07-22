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

from shelvery_tests.test_functions import addBackupTags, clusterCleanupBackups, clusterShareBackups, compareBackups, initCleanup, initCreateBackups, initSetup, initShareBackups

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.documentdb_backup import ShelveryDocumentDbBackup
from shelvery.engine import ShelveryEngine
from shelvery.engine import S3_DATA_PREFIX
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.aws_helper import AwsHelper
from shelvery_tests.conftest import destination_account

print(f"Python lib path:\n{sys.path}")


class ShelveryDocDBIntegrationTestCase(unittest.TestCase):
    """Shelvery DocDB Backups Integration shelvery tests"""

    def id(self):
        return str(self.__class__)

    def setUp(self):
        self.created_snapshots = []
        self.regional_snapshots = {
            'ap-southeast-1': [],
            'ap-southeast-2': []
        }
        os.environ['SHELVERY_MONO_THREAD'] = '1'

        # Complete initial setup and create service client
        initSetup(self,'docdb')
        docdbclient = AwsHelper.boto3_client('docdb', region_name='ap-southeast-2')

        #Wait till db is ready
        waiter = docdbclient.get_waiter('db_cluster_available')
        waiter.wait(
            DBClusterIdentifier='shelvery-test-docdb',
            WaiterConfig={
                'Delay': 30,
                'MaxAttempts': 50
            }
        )
 
        #Get cluster name
        clustername = f"arn:aws:rds:{os.environ['AWS_DEFAULT_REGION']}:{self.id['Account']}:cluster:shelvery-test-docdb"

        #Add tags to indicate backup
        addBackupTags(docdbclient,
                      clustername,
                      "shelvery-test-docdb")

        self.share_with_id = destination_account

    @pytest.mark.source
    def test_Cleanup(self):
        print(f"doc db - Running cleanup test")
        docdb_backups_engine = ShelveryDocumentDbBackup()
        backups = initCleanup(docdb_backups_engine)
        docdb_client = AwsHelper.boto3_client('docdb')

        valid = False
        for backup in backups:
            valid = clusterCleanupBackups(self=self,
                                  backup=backup,
                                  backup_engine=docdb_backups_engine,
                                  resource_client=docdb_client)

            valid = True
        
        self.assertTrue(valid)

    @pytest.mark.source
    def test_CreateDocDbBackup(self):

        print(f"docdb - Running backup test")

        docdb_cluster_backup_engine = ShelveryDocumentDbBackup()
        print(f"docdb - Shelvery backup initialised")
        
        backups = initCreateBackups(docdb_cluster_backup_engine)
        print("Created Doc DB Cluster backups")

        valid = False
        
        # validate there is
        for backup in backups:
            valid = compareBackups(self=self,
                           backup=backup,
                           backup_engine=docdb_cluster_backup_engine
                           )
        self.assertTrue(valid)

    @pytest.mark.source
    @pytest.mark.share
    def test_ShareDocDbBackup(self):
        print(f"doc db - Running share backup test")
        docdb_cluster_backup_engine = ShelveryDocumentDbBackup()

        print("Creating shared backups")
        backups = initShareBackups(docdb_cluster_backup_engine, str(self.share_with_id))

        print("Shared backups created")

        valid = False
        # validate there is
        for backup in backups:
            valid = clusterShareBackups(self=self,
                                       backup=backup,
                                       service='docdb'
            )

        

        self.assertTrue(valid)
   
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
