# import sys
# import traceback
# import unittest
# import pytest
# import yaml

# import boto3
# import os
# import time
# import botocore
# from datetime import datetime

# from shelvery_tests.test_functions import cleanEC2Snapshots, compareBackups, createBackupTags, ebsCleanupBackups, ebsPullBackups, initCleanup, initCreateBackups, initSetup, initShareBackups

# pwd = os.path.dirname(os.path.abspath(__file__))

# sys.path.append(f"{pwd}/..")
# sys.path.append(f"{pwd}/../shelvery")
# sys.path.append(f"{pwd}/shelvery")
# sys.path.append(f"{pwd}/lib")
# sys.path.append(f"{pwd}/../lib")

# from shelvery.ebs_backup import ShelveryEBSBackup
# from shelvery.engine import ShelveryEngine
# from shelvery.engine import S3_DATA_PREFIX
# from shelvery.runtime_config import RuntimeConfig
# from shelvery.backup_resource import BackupResource
# from shelvery.aws_helper import AwsHelper


# class ShelveryEBSPullTestCase(unittest.TestCase):
    
#     #@pytest.mark.destination
#     def test_PullEBSBackup(self):

#         os.environ['SHELVERY_MONO_THREAD'] = '1'
#         ebs_client = AwsHelper.boto3_client('ec2', region_name='ap-southeast-2')
#         ebs_backup_engine = ShelveryEBSBackup()

#         ebsPullBackups(self,ebs_client,ebs_backup_engine,'shelvery-test-ebs')
