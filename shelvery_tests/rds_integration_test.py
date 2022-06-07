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

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.rds_backup import ShelveryRDSBackup
from shelvery.engine import ShelveryEngine
from shelvery.engine import S3_DATA_PREFIX
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
            'us-east-1': [],
            'us-east-2': []
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
        print(f"rds - Creating RDS instance: {self}")
        # wait until db is available
        rdsinstance = rdsclient.describe_db_instances(DBInstanceIdentifier='shelvery-test-instance')['DBInstances'][0]
        while rdsinstance['DBInstanceStatus'] != 'available':
            time.sleep(15)
            rdsinstance = rdsclient.describe_db_instances(DBInstanceIdentifier='shelvery-test-instance')['DBInstances'][
                0]

        # add tags to resource
        response = rdsclient.add_tags_to_resource(
            ResourceName=rdsinstance['DBInstanceArn'],
            Tags=[
                {
                    'Key': f"{RuntimeConfig.get_tag_prefix()}:{ShelveryEngine.BACKUP_RESOURCE_TAG}",
                    'Value': 'true'
                }, {'Key': 'Name', 'Value': 'shelvery-automated-shelvery_tests'}]
        )
        print(f"Created RDS instance Arn: {self.id['Arn']}")
        print(f"Created RDS instance Account: {self.id['Account']}")
        self.share_with_id = int(self.id['Account']) + 1
        os.environ['shelvery_select_entity'] = rdsinstance['DBInstanceIdentifier']

    def test_CreateRdsBackup(self):
        print(f"rds - Running backup test")
        rds_backup_engine = ShelveryRDSBackup()
        print(f"rds - Shelvery backup initialised")
        try:
            print(f"rds - Execute create backups")
            backups = rds_backup_engine.create_backups()

        except Exception as e:
            print(e)
            print(f"Failed with {e}")
            traceback.print_exc(file=sys.stdout)
            raise e
        rdsclient = AwsHelper.boto3_client('rds')

        valid = False
        # validate there is
        for backup in backups:
            print("Inside backup loop" + backup.backup_id)
            snapshot_id = backup.backup_id
            self.created_snapshots.append(snapshot_id)

            # wait for snapshot to become available
            rds_backup_engine.wait_backup_available(backup.region, backup.backup_id, None, None)

            # allow buffer period for engine to write data to s3
            time.sleep(20)

            # this is the backup that gets stored in s3
            engine_backup = rds_backup_engine.get_backup_resource(backup.region, backup.backup_id)
            # verify the s3 data
            account_id = rds_backup_engine.account_id
            s3path = f"{S3_DATA_PREFIX}/{rds_backup_engine.get_engine_type()}/{engine_backup.name}.yaml"
            s3bucket = rds_backup_engine.get_local_bucket_name()
            print(f"Usingbucket {s3bucket}")
            print(f"Using path {s3path}")
            bucket = boto3.resource('s3').Bucket(s3bucket)
            object = bucket.Object(s3path)
            content = object.get()['Body'].read()
            restored_br = yaml.load(content, Loader=yaml.Loader)
            self.assertEqual(restored_br.backup_id, engine_backup.backup_id)
            self.assertEqual(restored_br.name, engine_backup.name)
            self.assertEqual(restored_br.region, engine_backup.region)
            print(f"Tags restored: \n{yaml.dump(restored_br.tags)}\n")
            print(f"Tags backup: \n{yaml.dump(engine_backup.tags)}\n")
            self.assertEqual(restored_br.tags['Name'], engine_backup.tags['Name'])
            for tag in ['name', 'date_created', 'entity_id', 'region', 'retention_type']:
                self.assertEqual(
                    restored_br.tags[f"{RuntimeConfig.get_tag_prefix()}:{tag}"],
                    engine_backup.tags[f"{RuntimeConfig.get_tag_prefix()}:{tag}"]
                )
            valid = True
        self.assertTrue(valid)

    def tearDown(self):
        print("rds - tear down rds instance")
        rdsclient = AwsHelper.boto3_client('rds', region_name='us-east-1')
        for snapid in self.created_snapshots:
            print(f"Deleting snapshot {snapid}")
            try:
                rdsclient.delete_db_snapshot(DBSnapshotIdentifier=snapid)
            except Exception as e:
                print(f"Failed to delete {snapid}:{str(e)}")

        response = rdsclient.delete_db_instance(DBInstanceIdentifier='shelvery-test-instance',
                                                SkipFinalSnapshot=True)
        print("rds - snapshot deleted, instance deleting")


if __name__ == '__main__':
    unittest.main()
