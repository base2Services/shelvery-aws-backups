# import sys
# import traceback
# from turtle import back
# import unittest
# import pytest
# import yaml

# import boto3
# import os
# import time
# import botocore
# from datetime import datetime
# from shelvery import aws_helper
# from shelvery_tests.test_functions import addBackupTags, compareBackups, initCleanup, initCreateBackups, initSetup, initShareBackups, instanceCleanupBackups, instanceShareBackups

# pwd = os.path.dirname(os.path.abspath(__file__))

# sys.path.append(f"{pwd}/..")
# sys.path.append(f"{pwd}/../shelvery")
# sys.path.append(f"{pwd}/shelvery")
# sys.path.append(f"{pwd}/lib")
# sys.path.append(f"{pwd}/../lib")

# from shelvery.rds_backup import ShelveryRDSBackup
# from shelvery.engine import ShelveryEngine
# from shelvery.engine import S3_DATA_PREFIX
# from shelvery.runtime_config import RuntimeConfig
# from shelvery.backup_resource import BackupResource
# from shelvery.aws_helper import AwsHelper
# from shelvery_tests.conftest import destination_account

# print(f"Python lib path:\n{sys.path}")


# class ShelveryRDSIntegrationTestCase(unittest.TestCase):
#     """Shelvery RDS Backups Integration shelvery tests"""

#     def id(self):
#         return str(self.__class__)


#     def setUp(self):
#         self.created_snapshots = []
#         self.regional_snapshots = {
#             'ap-southeast-1': [],
#             'ap-southeast-2': []
#         }
#         os.environ['SHELVERY_MONO_THREAD'] = '1'

#         # Create and configure RDS artefact
#         initSetup(self,'rds')
#         rdsclient = AwsHelper.boto3_client('rds', region_name='ap-southeast-2')
        
#         #Get db instance name
#         rdsinstance = rdsclient.describe_db_instances(DBInstanceIdentifier='shelvery-test-rds')['DBInstances'][0]  
        
#         # add tags to resource
#         addBackupTags(rdsclient,
#                       rdsinstance['DBInstanceArn'],
#                       "shelvery-test-rds")

#         self.share_with_id = destination_account

#    # @pytest.mark.source
#     def test_Cleanup(self):
#         print(f"rds - Running cleanup test")
#         rds_backups_engine = ShelveryRDSBackup()
#         backups = initCleanup(rds_backups_engine)
#         rds_client = AwsHelper.boto3_client('rds')

#         valid = False
#         for backup in backups:
#             valid = instanceCleanupBackups(self=self,
#                                    backup=backup,
#                                    backup_engine=rds_backups_engine,
#                                    service_client=rds_client
#                                    )
        
#         self.assertTrue(valid)

#    # @pytest.mark.source
#     def test_CreateRdsBackup(self):
#         print(f"rds - Running backup test")

#         rds_backup_engine = ShelveryRDSBackup()
#         print(f"rds - Shelvery backup initialised")

#         backups = initCreateBackups(rds_backup_engine)
#         print("Created RDS backups")

#         valid = False

#         # validate there is
#         for backup in backups:
#             valid = compareBackups(self=self,
#                            backup=backup,
#                            backup_engine=rds_backup_engine
#                            )
#         self.assertTrue(valid)

#    # @pytest.mark.source
#    # @pytest.mark.share
#     def test_shareRdsBackup(self):
        
#         print(f"rds - Running share backup test")
#         rds_backups_engine = ShelveryRDSBackup()

#         backups = initShareBackups(rds_backups_engine, str(self.share_with_id))
        
#         print("Shared backups created")

#         valid = False
#         # validate there is
#         for backup in backups:
#             valid = instanceShareBackups(self=self,
#                                  backup=backup
#                                  )

#         self.assertTrue(valid)

#     def tearDown(self):
#         print("rds - tear down rds instance")
#         rdsclient = AwsHelper.boto3_client('rds', region_name='ap-southeast-2')
#         for snapid in self.created_snapshots:
#             print(f"Deleting snapshot {snapid}")
#             try:
#                 rdsclient.delete_db_snapshot(DBSnapshotIdentifier=snapid)
#             except Exception as e:
#                 print(f"Failed to delete {snapid}:{str(e)}")

#         print("rds - snapshot deleted, instance deleting")


# if __name__ == '__main__':
#     unittest.main()
