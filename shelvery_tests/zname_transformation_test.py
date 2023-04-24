import sys
import traceback
import unittest
import os
import time
import pytest

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.ebs_backup import ShelveryEBSBackup
from shelvery.engine import ShelveryEngine
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource
from shelvery.aws_helper import AwsHelper

print(f"Python lib path:\n{sys.path}")

NAME_WITH_SPECIAL_CHARACTERS = 'shelvery&#^--_auto_mate_d_tests'
NAME_TRANSFORMED = 'shelvery-auto-mate-d-tests'


class ShelveryNameTransformationTestCase(unittest.TestCase):
    """Shelvery EBS Backups Integration shelvery_tests"""
    
    def id(self):
        return str(self.__class__)
    
    @pytest.mark.source
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
                                                  }, {'Key': 'Name', 'Value': NAME_WITH_SPECIAL_CHARACTERS}]
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
    
    @pytest.mark.source
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
    def test_NameTransformed(self):
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
                snapshots = ec2client.describe_snapshots(SnapshotIds=[snapshot_id])['Snapshots']
                self.assertTrue(len(snapshots) == 1)
                self.assertTrue(snapshots[0]['VolumeId'] == self.volume['VolumeId'])
                d_tags = dict(map(lambda x: (x['Key'], x['Value']), snapshots[0]['Tags']))

                self.assertTrue(d_tags['Name'].startswith(NAME_TRANSFORMED))
                print(f"required: {backup.date_created.strftime(BackupResource.TIMESTAMP_FORMAT)}-{backup.retention_type}")
                print(f"actual: {d_tags['Name']}")
                self.assertTrue(d_tags['Name'].endswith(f"{backup.date_created.strftime(BackupResource.TIMESTAMP_FORMAT)}-{backup.retention_type}"))
                
                valid = True
        
        self.assertTrue(valid)
    

if __name__ == '__main__':
    unittest.main()
