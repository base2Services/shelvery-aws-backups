import sys
import unittest

import boto3
import os

pwd = os.path.dirname(os.path.abspath(__file__))
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.ebs_backup import ShelveryEBSBackup
from shelvery.engine import ShelveryEngine
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource

print(f"Python lib path:\n{sys.path}")


class ShelveryEBSIntegrationTestCase(unittest.TestCase):
    """Shelvery Factory unit tests"""
    
    def setUp(self):
        self.volume = None
        self.created_snapshots = []
        
        print(f"Setting up ebs integraion test")
        print("Create EBS Volume of 1G")
        os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')
        ec2client = boto3.client('ec2')
        sts = boto3.client('sts')
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
                                                  }, {'Key': 'Name', 'Value': 'shelvery-automated-tests'}]
                                              }])
        print(f"Created volume: {self.volume}")
        # TODO wait until volume is 'available'
        self.share_with_id = int(self.id['Account']) + 1
    
    def tearDown(self):
        ec2client = boto3.client('ec2')
        ec2client.delete_volume(VolumeId=self.volume['VolumeId'])
        for snapid in self.created_snapshots:
            ec2client.delete_snapshot(SnapshotId=snapid)
    
    def test_CreateBackups(self):
        ebs_backups_engine = ShelveryEBSBackup()
        try:
            backups = ebs_backups_engine.create_backups()
        except Exception as e:
            print(e)
            print(f"Failed with {e}")
            raise e
        ec2client = boto3.client('ec2')
        
        valid = False
        # validate there is
        for backup in backups:
            if backup.entity_id == self.volume['VolumeId']:
                snapshot_id = backup.backup_id
                snapshots = ec2client.describe_snapshots(SnapshotIds=[snapshot_id])['Snapshots']
                self.assertTrue(len(snapshots) == 1)
                self.assertTrue(snapshots[0]['VolumeId'] == self.volume['VolumeId'])
                d_tags = dict(map(lambda x: (x['Key'], x['Value']), snapshots[0]['Tags']))
                marker_tag = f"{RuntimeConfig.get_tag_prefix()}:{BackupResource.BACKUP_MARKER_TAG}"
                self.assertTrue(marker_tag in d_tags)
                self.assertTrue(f"{RuntimeConfig.get_tag_prefix()}:entity_id" in d_tags)
                self.assertTrue(d_tags[f"{RuntimeConfig.get_tag_prefix()}:entity_id"] == self.volume['VolumeId'])
                valid = True
                self.created_snapshots.append(snapshot_id)
        
        self.assertTrue(valid)
    
    def test_ShareBackups(self):
        ebs_backups_engine = ShelveryEBSBackup()
        try:
            os.environ.setdefault('shelvery_share_aws_account_ids', self.share_with_id)
            backups = ebs_backups_engine.create_backups()
        except Exception as e:
            print(e)
            print(f"Failed with {e}")
            raise e
        
        ec2 = boto3.resource('ec2')
        valid = False
        # validate there is
        for backup in backups:
            if backup.entity_id == self.volume['VolumeId']:
                snapshot_id = backup.backup_id
                snapshot = ec2.Snapshot(snapshot_id)
                attr = snapshot.describe_attribute(Attribute='createVolumePermission')
                print(f"CreateVolumePermissions: {attr}")
                userlist = attr['CreateVolumePermissions']
                self.assertTrue(str(self.share_with_id) in list(map(lambda x: x['UserId'], userlist)))
                valid = True
                self.created_snapshots.append(snapshot_id)
        
        self.assertTrue(valid)


if __name__ == '__main__':
    unittest.main()
