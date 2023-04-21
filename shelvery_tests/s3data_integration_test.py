import sys
import traceback
import unittest
import yaml
import boto3
import os
import time
import botocore
import pytest
from datetime import datetime

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.ebs_backup import ShelveryEBSBackup
from shelvery.engine import ShelveryEngine
from shelvery.engine import S3_DATA_PREFIX
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.aws_helper import AwsHelper


print(f"Python lib path:\n{sys.path}")


class ShelveryS3DataTestCase(unittest.TestCase):
    """Shelvery EBS Backups Integration shelvery_tests"""
    
    def id(self):
        return str(self.__class__)
    
    def setUp(self):
        self.volume = None
        self.created_snapshots = []
        self.regional_snapshots = {
            'us-west-1': [],
            'us-west-2': []
        }
        
        print(f"Setting up ebs integraion test")
        print("Create EBS Volume of 1G")
        os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
        os.environ['SHELVERY_MONO_THREAD'] = '1'
        ec2client = AwsHelper.boto3_client('ec2')
        sts = AwsHelper.boto3_client('sts')
        self.id = sts.get_caller_identity()
        print(f"Running as user:\n{self.id}\n")
        self.volume = ec2client.create_volume(AvailabilityZone='us-east-1a',
                                              Encrypted=False,
                                              Size=1,
                                              VolumeType='gp2',
                                              TagSpecifications=[{
                                                  'ResourceType': 'volume',
                                                  'Tags': [{
                                                      'Key': f"{RuntimeConfig.get_tag_prefix()}:{ShelveryEngine.BACKUP_RESOURCE_TAG}",
                                                      'Value': 'true'
                                                  }, {'Key': 'Name', 'Value': 'shelvery-automated-shelvery_tests'}]
                                              }])
        
        # wait until volume is available
        interm_volume = ec2client.describe_volumes(VolumeIds=[self.volume['VolumeId']])['Volumes'][0]
        while interm_volume['State'] != 'available':
            time.sleep(5)
            interm_volume = ec2client.describe_volumes(VolumeIds=[self.volume['VolumeId']])['Volumes'][0]
        
        print(f"Created volume: {self.volume}")
        # TODO wait until volume is 'available'
        self.share_with_id = int(self.id['Account']) + 1
        os.environ['shelvery_select_entity'] = self.volume['VolumeId']

    def tearDown(self):
        ec2client = AwsHelper.boto3_client('ec2')
        ec2client.delete_volume(VolumeId=self.volume['VolumeId'])
        print(f"Deleted volume:\n{self.volume['VolumeId']}\n")
        
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
                    
    @pytest.mark.source
    def test_CreateBackupData(self):
        ebs_backups_engine = ShelveryEBSBackup()
        try:
            backups = ebs_backups_engine.create_backups()
        except Exception as e:
            print(e)
            print(f"Failed with {e}")
            traceback.print_exc(file=sys.stdout)
            raise e
        ec2client = AwsHelper.boto3_client('ec2')
        
        valid = False
        # validate there is
        for backup in backups:
            if backup.entity_id == self.volume['VolumeId']:
                snapshot_id = backup.backup_id
                self.created_snapshots.append(snapshot_id)
                
                # wait for snapshot to become available
                ebs_backups_engine.wait_backup_available(backup.region, backup.backup_id, None, None)
                
                # allow buffer period for engine to write data to s3
                time.sleep(20)
                
                # this is the backup that gets stored in s3
                engine_backup = ebs_backups_engine.get_backup_resource(backup.region, backup.backup_id)
                # verify the s3 data
                account_id = ebs_backups_engine.account_id
                s3path = f"{S3_DATA_PREFIX}/{ebs_backups_engine.get_engine_type()}/{engine_backup.name}.yaml"
                s3bucket = ebs_backups_engine.get_local_bucket_name()
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
                for tag in ['name','date_created','entity_id','region','retention_type']:
                    self.assertEqual(
                        restored_br.tags[f"{RuntimeConfig.get_tag_prefix()}:{tag}"],
                        engine_backup.tags[f"{RuntimeConfig.get_tag_prefix()}:{tag}"]
                    )
                valid = True
        
        self.assertTrue(valid)
    
    @pytest.mark.source
    def test_CreateSharingInfo(self):
        ebs_backups_engine = ShelveryEBSBackup()
        try:
            os.environ["shelvery_share_aws_account_ids"] = str(self.share_with_id)
            backups = ebs_backups_engine.create_backups()
        except Exception as e:
            print(e)
            print(f"Failed with {e}")
            traceback.print_exc(file=sys.stdout)
            raise e
        finally:
            del os.environ["shelvery_share_aws_account_ids"]
        
        valid = False
        for backup in backups:
            if backup.entity_id == self.volume['VolumeId']:
                account_id = ebs_backups_engine.account_id
                s3path = f"{S3_DATA_PREFIX}/shared/{self.share_with_id}/{ebs_backups_engine.get_engine_type()}/{backup.name}.yaml"
                s3bucket = ebs_backups_engine.get_local_bucket_name()
                bucket = boto3.resource('s3').Bucket(s3bucket)
                object = bucket.Object(s3path)
                content = object.get()['Body'].read()
                restored_br = yaml.load(content, Loader=yaml.Loader)
                engine_backup = ebs_backups_engine.get_backup_resource(backup.region, backup.backup_id)
                self.assertEqual(restored_br.backup_id, engine_backup.backup_id)
                self.assertEqual(restored_br.name, engine_backup.name)
                self.assertEqual(restored_br.region, engine_backup.region)
                print(engine_backup.name)
                for tag in ['name','date_created','entity_id','region','retention_type']:
                    self.assertEqual(
                        restored_br.tags[f"{RuntimeConfig.get_tag_prefix()}:{tag}"],
                        engine_backup.tags[f"{RuntimeConfig.get_tag_prefix()}:{tag}"]
                    )
                valid = True
        
        self.assertTrue(valid)

    @pytest.mark.source
    def test_CleanBackupData(self):
        ebs_backups_engine = ShelveryEBSBackup()
        try:
            backups = ebs_backups_engine.create_backups()
        except Exception as e:
            print(e)
            print(f"Failed with {e}")
            traceback.print_exc(file=sys.stdout)
            raise e
        ec2client = AwsHelper.boto3_client('ec2')
        
        valid = False
        # validate there is
        for backup in backups:
            if backup.entity_id == self.volume['VolumeId']:
                snapshot_id = backup.backup_id
                snapshots = ec2client.describe_snapshots(SnapshotIds=[snapshot_id])['Snapshots']
                self.assertEqual(len(snapshots), 1)
                ec2client.create_tags(
                    Resources=[snapshot_id],
                    Tags=[{'Key': f"{RuntimeConfig.get_tag_prefix()}:date_created",
                           'Value': datetime(2000, 1, 1).strftime(BackupResource.TIMESTAMP_FORMAT)
                           }]
                )
                ebs_backups_engine.clean_backups()
                with self.assertRaises(botocore.exceptions.ClientError) as context:
                    ec2client.describe_snapshots(SnapshotIds=[snapshot_id])['Snapshots']
                
                self.assertTrue('does not exist' in context.exception.response['Error']['Message'])
                self.assertEqual('InvalidSnapshot.NotFound', context.exception.response['Error']['Code'])
                
                account_id = ebs_backups_engine.account_id
                s3path = f"{S3_DATA_PREFIX}/{ebs_backups_engine.get_engine_type()}/removed/{backup.name}.yaml"
                s3bucket = ebs_backups_engine.get_local_bucket_name()
                bucket = boto3.resource('s3').Bucket(s3bucket)
                object = bucket.Object(s3path)
                content = object.get()['Body'].read()
                restored_br = yaml.load(content, Loader=yaml.Loader)
                self.assertEqual(restored_br.backup_id, backup.backup_id)
                self.assertEqual(restored_br.name, backup.name)
                self.assertEqual(restored_br.region, backup.region)
                self.assertIsNotNone(restored_br.date_deleted)
                self.assertEqual(restored_br.date_created, datetime(2000, 1, 1))
                valid = True
        
        self.assertTrue(valid)


if __name__ == '__main__':
    unittest.main()
