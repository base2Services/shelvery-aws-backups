import sys
import traceback
import unittest

import boto3
import os
import time
import botocore
from datetime import datetime

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.rds_backup import ShelveryRDSBackup
from shelvery.engine import ShelveryEngine
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.aws_helper import AwsHelper

print(f"Python lib path:\n{sys.path}")


class ShelveryRDSIntegrationTestCase(unittest.TestCase):
    """Shelvery RDS Backups Integration shelvery tests"""

    def id(self):
        return str(self.__class__)

    def setUp(self):
        self.volume = None
        self.created_snapshots = []
        self.regional_snapshots = {
            'us-west-1': [],
            'us-west-2': []
        }

        # Create and configure RDS artefact
        print(f"Setting up rds integration test")
        print("Create rds instance")
        os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
        os.environ['SHELVERY_MONO_THREAD'] = '1'
        rdsclient = AwsHelper.boto3_client('rds', region_name='us-east-1')
        sts = AwsHelper.boto3_client('sts')
        self.id = sts.get_caller_identity()
        print(f"Running as user:\n{self.id}\n")
        self.volume = rdsclient.create_db_instance(Engine='mysql',
                                                   DBName='Someting',
                                                   AllocatedStorage=10,
                                                   DBInstanceClass='db.t3.micro',
                                                   DBInstanceIdentifier="shelvery-test-instance",
                                                   MasterUsername='someuser',
                                                   MasterUserPassword='bananas1',
                                                   Port=3306,
                                                   BackupRetentionPeriod=0)

        # wait until db is available
        rdsinstance = rdsclient.describe_db_instances(DBInstanceIdentifier='shelvery-test-instance')['DBInstances'][0]
        while rdsinstance['DBInstanceStatus'] != 'available':
            time.sleep(5)
            rdsinstance = rdsclient.describe_db_instances(DBInstanceIdentifier='shelvery-test-instance')['DBInstances'][0]

        # add tags to resource
        response = rdsclient.add_tags_to_resource(
            ResourceName=rdsinstance['DBInstanceArn'],
            Tags=[
                {
                    'Key': f"{RuntimeConfig.get_tag_prefix()}:{ShelveryEngine.BACKUP_RESOURCE_TAG}",
                    'Value': 'true'
                }, {'Key': 'Name', 'Value': 'shelvery-automated-shelvery_tests'}]
        )
        print(f"Created RDS instance: {self.id['Arn']}")


    def test_CreateBackups(self):
        rds_backup_engine = ShelveryRDSBackup()
        try:
            backups = rds_backup_engine.create_backups()
            print(backups)
        except Exception as e:
            print(e)
            print(f"Failed with {e}")
            traceback.print_exc(file=sys.stdout)
            raise e
        rdsclient = AwsHelper.boto3_client('rds')

if __name__ == '__main__':
    unittest.main()