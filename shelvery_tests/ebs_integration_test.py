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

from shelvery.ebs_backup import ShelveryEBSBackup
from shelvery.engine import ShelveryEngine
from shelvery.runtime_config import RuntimeConfig
from shelvery.backup_resource import BackupResource

print(f"Python lib path:\n{sys.path}")


class ShelveryEBSIntegrationTestCase(unittest.TestCase):
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
        ec2client = boto3.client('ec2')
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
            ec2regional = boto3.client('ec2', region_name=region)
            for snapid in self.regional_snapshots[region]:
                try:
                    ec2regional.delete_snapshot(SnapshotId=snapid)
                except Exception as e:
                    print(f"Failed to delete {snapid}:{str(e)}")

    def test_CreateBackups(self):
        ebs_backups_engine = ShelveryEBSBackup()
        try:
            backups = ebs_backups_engine.create_backups()
        except Exception as e:
            print(e)
            print(f"Failed with {e}")
            traceback.print_exc(file=sys.stdout)
            raise e
        ec2client = boto3.client('ec2')

        valid = False
        # validate there is
        for backup in backups:
            if backup.entity_id == self.volume['VolumeId']:
                snapshot_id = backup.backup_id
                self.created_snapshots.append(snapshot_id)
                snapshots = ec2client.describe_snapshots(SnapshotIds=[snapshot_id])['Snapshots']
                self.assertTrue(len(snapshots) == 1)
                self.assertTrue(snapshots[0]['VolumeId'] == self.volume['VolumeId'])
                d_tags = dict(map(lambda x: (x['Key'], x['Value']), snapshots[0]['Tags']))
                marker_tag = f"{RuntimeConfig.get_tag_prefix()}:{BackupResource.BACKUP_MARKER_TAG}"
                self.assertTrue(marker_tag in d_tags)
                self.assertTrue(f"{RuntimeConfig.get_tag_prefix()}:entity_id" in d_tags)
                self.assertTrue(d_tags[f"{RuntimeConfig.get_tag_prefix()}:entity_id"] == self.volume['VolumeId'])
                valid = True

        self.assertTrue(valid)

    def test_ShareBackups(self):
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

        ec2 = boto3.resource('ec2')
        valid = False
        # validate there is
        for backup in backups:
            if backup.entity_id == self.volume['VolumeId']:
                print(f"Testing snap {backup.entity_id} if shared with {self.share_with_id}")
                snapshot_id = backup.backup_id
                self.created_snapshots.append(snapshot_id)
                snapshot = ec2.Snapshot(snapshot_id)
                attr = snapshot.describe_attribute(Attribute='createVolumePermission')
                print(f"CreateVolumePermissions: {attr}")
                userlist = attr['CreateVolumePermissions']
                self.assertTrue(str(self.share_with_id) in list(map(lambda x: x['UserId'], userlist)))
                valid = True

        self.assertTrue(valid)

    def test_CopyBackups(self):
        ebs_backups_engine = ShelveryEBSBackup()
        try:
            os.environ['shelvery_dr_regions'] = 'us-west-2'
            backups = ebs_backups_engine.create_backups()
        except Exception as e:
            print(e)
            print(f"Failed with {e}")
            traceback.print_exc(file=sys.stdout)
            raise e
        finally:
            del os.environ["shelvery_dr_regions"]

        ec2dr_region = boto3.client('ec2', region_name='us-west-2')
        valid = False
        # validate there is
        for backup in backups:
            if backup.entity_id == self.volume['VolumeId']:
                print(
                    f"Testing snap {backup.entity_id} if copied to region us-west-2")
                snapshot_id = backup.backup_id
                self.created_snapshots.append(snapshot_id)
                drsnapshot = ec2dr_region.describe_snapshots(Filters=[
                    {'Name': f"tag:{RuntimeConfig.get_tag_prefix()}:entity_id",
                     'Values': [self.volume['VolumeId']]
                     }])['Snapshots'][0]
                drsnapshot_dtags = dict(map(lambda x: (x['Key'], x['Value']), drsnapshot['Tags']))

                tag_key = f"{RuntimeConfig.get_tag_prefix()}:dr_copy"
                tag_value = 'true'
                self.assertTrue(tag_key in drsnapshot_dtags)
                self.assertEquals(drsnapshot_dtags[tag_key], tag_value)

                tag_key = f"{RuntimeConfig.get_tag_prefix()}:dr_source_backup"
                tag_value = f"us-east-1:{snapshot_id}"
                self.assertTrue(tag_key in drsnapshot_dtags)
                self.assertEquals(drsnapshot_dtags[tag_key], tag_value)

                tag_key = f"{RuntimeConfig.get_tag_prefix()}:region"
                tag_value = 'us-west-2'
                self.assertTrue(tag_key in drsnapshot_dtags)
                self.assertEquals(drsnapshot_dtags[tag_key], tag_value)

                self.regional_snapshots['us-west-2'].append(drsnapshot['SnapshotId'])
                valid = True

        self.assertTrue(valid)

    def test_CleanBackups(self):
        ebs_backups_engine = ShelveryEBSBackup()
        try:
            backups = ebs_backups_engine.create_backups()
        except Exception as e:
            print(e)
            print(f"Failed with {e}")
            traceback.print_exc(file=sys.stdout)
            raise e
        ec2client = boto3.client('ec2')

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
                           'Value': datetime(1990, 1, 1).strftime(BackupResource.TIMESTAMP_FORMAT)
                           }]
                )
                ebs_backups_engine.clean_backups()
                with self.assertRaises(botocore.exceptions.ClientError) as context:
                    ec2client.describe_snapshots(SnapshotIds=[snapshot_id])['Snapshots']

                self.assertTrue('does not exist' in context.exception.response['Error']['Message'])
                self.assertEqual('InvalidSnapshot.NotFound', context.exception.response['Error']['Code'])
                valid = True

        self.assertTrue(valid)


if __name__ == '__main__':
    unittest.main()
