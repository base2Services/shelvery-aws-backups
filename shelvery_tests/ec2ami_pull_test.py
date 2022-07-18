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

from shelvery_tests.test_functions import cleanEC2Snapshots, compareBackups, createBackupTags, ec2CleanupBackups, ec2PullBackups, ec2ShareBackups, initCleanup, initCreateBackups, initSetup, initShareBackups

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


class ShelveryEC2AmiPullTestCase(unittest.TestCase):
    
    @pytest.mark.destination
    def test_PullEC2Backup(self):

        print(f"ec2 - Running pull shared backups test")
    
        ec2_client = AwsHelper.boto3_client('ec2', region_name='ap-southeast-2')
        ec2_backup_engine = ShelveryEC2AMIBackup()

        ec2PullBackups(self,ec2_client,ec2_backup_engine)

    @pytest.mark.cleanup
    def test_cleanup(self):
        cleanEC2Snapshots()
