#Functions used to compare snapshots/clusters/instances 
from datetime import datetime
from shelvery.backup_resource import BackupResource
from shelvery.engine import ShelveryEngine
from shelvery.runtime_config import RuntimeConfig
from shelvery.aws_helper import AwsHelper
import traceback
import sys
import os
import boto3
import time
import yaml
from shelvery_tests.conftest import destination_account, source_account
from shelvery_tests.cleanup_functions import cleanEC2Snapshots

def add_backup_tags(client,resource_name,tag_value):
    response = client.add_tags_to_resource(
            ResourceName=resource_name,
            Tags=[{
                    'Key': f"{RuntimeConfig.get_tag_prefix()}:{ShelveryEngine.BACKUP_RESOURCE_TAG}",
                    'Value': 'true'
                    }, {'Key': 'Name', 'Value': tag_value}]
        )
    
    return response

def createBackupTags(client,resource_list,tag_value):
    response = client.create_tags(
            Resources=resource_list,
            Tags=[{
                    'Key': f"{RuntimeConfig.get_tag_prefix()}:{ShelveryEngine.BACKUP_RESOURCE_TAG}",
                    'Value': 'true'
                    }, {'Key': 'Name', 'Value': tag_value}]
        )
    return response

def setup(self,service_name):
    print(f"Starting {service_name} integration test")
    self.created_snapshots = []
    self.share_with_id = destination_account
    os.environ['AWS_DEFAULT_REGION'] = 'ap-southeast-2'
    os.environ['SHELVERY_MONO_THREAD'] = '1'
    os.environ['shelvery_custom_retention_types'] = 'shortLived:1'
    os.environ['shelvery_current_retention_type'] = 'shortLived'
    
    sts = AwsHelper.boto3_client('sts')
    self.id = sts.get_caller_identity()
    print(f"Running as user:\n{self.id}\n")

def share_backups(backup_engine, share_with_id):
        try:
            os.environ["shelvery_share_aws_account_ids"] = str(share_with_id)
            backups = backup_engine.create_backups()
        except Exception as e:
            print(e)
            print(f"Failed with {e}")
            traceback.print_exc(file=sys.stdout)
            raise e
        finally:
            del os.environ["shelvery_share_aws_account_ids"]

        return backups


def compare_backups(self,backup,backup_engine):
    print("Inside backup loop" + backup.backup_id)
    snapshot_id = backup.backup_id
    self.created_snapshots.append(snapshot_id)
    print("Snapshot:" + str(snapshot_id))

    # wait for snapshot to become available
    backup_engine.wait_backup_available(backup.region, backup.backup_id, None, None)

    # allow buffer period for engine to write data to s3
    time.sleep(20)

    # this is the backup that gets stored in s3
    engine_backup = backup_engine.get_backup_resource(backup.region, backup.backup_id)
    # verify the s3 data
    account_id = backup_engine.account_id
    s3path = f"backups/{backup_engine.get_engine_type()}/{engine_backup.name}.yaml"
    s3bucket = backup_engine.get_local_bucket_name()
    print(f"Using bucket {s3bucket}")
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
    
    return True

def cluster_share_backups(self, backup, service):
    print(f"BackupId={backup.backup_id}")
    print(f"Accountd={backup.account_id}")

    snapshot_id = backup.backup_id
    print(f"Testing if snapshot {snapshot_id} is shared with {self.share_with_id}")
   
    source_client = AwsHelper.boto3_client(service)

    #Get source snapshot
    source_snapshot = source_client.describe_db_cluster_snapshots(
        DBClusterIdentifier=backup.entity_id,
        DBClusterSnapshotIdentifier=snapshot_id
    )

    attributes = source_client.describe_db_cluster_snapshot_attributes(
        DBClusterSnapshotIdentifier=snapshot_id
    )['DBClusterSnapshotAttributesResult']['DBClusterSnapshotAttributes']

    #Restore attribute indicating restoreable snapshot
    restore_attribute = [attr for attr in attributes if attr['AttributeName'] == 'restore'][0]['AttributeValues']

    print("Attributes: " + str(restore_attribute))

    #Assert Snapshot(s) exist
    self.assertTrue(len(source_snapshot['DBClusterSnapshots']) ==1)

    #Assert that snapshot is shared with dest account
    self.assertTrue(destination_account in restore_attribute)

    return True

def cluster_cleanup_backups(self, backup, backup_engine, resource_client):
    snapshot_id = backup.backup_id
      
    #Get source snapshot
    precleanup_snapshots = resource_client.describe_db_cluster_snapshots(
        DBClusterIdentifier=backup.entity_id,
        DBClusterSnapshotIdentifier=snapshot_id
    )

    #Snapshot before cleanup
    print("Pre-Cleanup Snapshots: " + str(precleanup_snapshots))

    #Assert Snapshot(s) exist
    self.assertTrue(len(precleanup_snapshots['DBClusterSnapshots']) ==1)

    snapshot_arn = precleanup_snapshots['DBClusterSnapshots'][0]['DBClusterSnapshotArn']

    #Set cleanup date
    resource_client.add_tags_to_resource(
            ResourceName=snapshot_arn,
            Tags=[{'Key': f"{RuntimeConfig.get_tag_prefix()}:date_created",
                    'Value': datetime(1990, 1, 1).strftime(BackupResource.TIMESTAMP_FORMAT)
                    }]
        )

    backup_engine.clean_backups()

    #Get post cleanup snapshots
    postcleanup_snapshots = resource_client.describe_db_cluster_snapshots(
        DBClusterIdentifier=backup.entity_id,
        DBClusterSnapshotIdentifier=snapshot_id
    )

    #Snapshot after cleanup
    print("Post-Cleanup Snapshots: " + str(postcleanup_snapshots))

    #Ensure cleanup removed all snapshots
    self.assertTrue(len(postcleanup_snapshots['DBClusterSnapshots']) == 0)

    return True

def instance_share_backups(self,backup):
    print(f"BackupId={backup.backup_id}")
    print(f"Accountd={backup.account_id}")

    snapshot_id = backup.backup_id
    print(f"Testing if snapshot {snapshot_id} is shared with {self.share_with_id}")
    
    source_client = AwsHelper.boto3_client('rds')

    #Get source snapshot
    source_snapshot = source_client.describe_db_snapshots(
        DBInstanceIdentifier=backup.entity_id,
        DBSnapshotIdentifier=snapshot_id
    )
    
    attributes = source_client.describe_db_snapshot_attributes(
        DBSnapshotIdentifier=snapshot_id
    )['DBSnapshotAttributesResult']['DBSnapshotAttributes']

    #Restore attribute indicating restoreable snapshot
    restore_attribute = [attr for attr in attributes if attr['AttributeName'] == 'restore'][0]['AttributeValues']
    
    print("Attributes: " + str(restore_attribute))

    #Assert Snapshot(s) exist
    self.assertTrue(len(source_snapshot['DBSnapshots']) ==1)

    #Assert that snapshot is shared with dest account
    self.assertTrue(destination_account in restore_attribute)

    return True

def instance_cleanup_backups(self,backup,backup_engine,service_client):
    snapshot_id = backup.backup_id
      
    #Get source snapshot
    precleanup_snapshots = service_client.describe_db_snapshots(
        DBInstanceIdentifier=backup.entity_id,
        DBSnapshotIdentifier=snapshot_id
    )

    #Snapshot before cleanup
    print("Pre-Cleanup Snapshots: " + str(precleanup_snapshots))

    #Assert Snapshot(s) exist
    self.assertTrue(len(precleanup_snapshots['DBSnapshots']) ==1)

    snapshot_arn = precleanup_snapshots['DBSnapshots'][0]['DBSnapshotArn']
    
    #Set cleanup date
    service_client.add_tags_to_resource(
            ResourceName=snapshot_arn,
            Tags=[{'Key': f"{RuntimeConfig.get_tag_prefix()}:date_created",
                    'Value': datetime(1990, 1, 1).strftime(BackupResource.TIMESTAMP_FORMAT)
                    }]
        )

    backup_engine.clean_backups()

    #Get post cleanup snapshots
    postcleanup_snapshots = service_client.describe_db_snapshots(
        DBInstanceIdentifier=backup.entity_id,
        DBSnapshotIdentifier=snapshot_id
    )

    #Snapshot after cleanup
    print("Post-Cleanup Snapshots: " + str(postcleanup_snapshots))

    #Ensure cleanup removed all snapshots
    self.assertTrue(len(postcleanup_snapshots['DBSnapshots']) == 0)

    return True

def ec2_share_backups(self,backup):
    print(f"BackupId={backup.backup_id}")
    print(f"Accountd={backup.account_id}")

    snapshot_name = backup.name
    
    source_client = AwsHelper.boto3_client('ec2')

    print(f"Testing if snapshot {snapshot_name} is shared with {self.share_with_id}")

    #Get source snapshot
    source_snapshot = source_client.describe_snapshots( 
        Filters = [{
            'Name': 'tag:Name',
            'Values': [
                snapshot_name
            ]
        }]
    )

    snapshot_id = source_snapshot['Snapshots'][0]['SnapshotId']

    attributes = source_client.describe_snapshot_attribute(
        Attribute='createVolumePermission',
        SnapshotId=snapshot_id,
    )['CreateVolumePermissions']

    #Restore attribute indicating restoreable snapshot
    restore_attribute = [attr for attr in attributes if attr['UserId'] == destination_account]

    print("Attributes: " + str(restore_attribute))

    #Assert Snapshot(s) exist
    self.assertTrue(len(source_snapshot['Snapshots']) ==1)

     #Assert that snapshot is shared with dest account
    self.assertTrue(len(restore_attribute) == 1)

    return True

def ebs_cleanup_backups(self,backup,backup_engine,service_client):
    snapshot_id = backup.name
      
    #Get pre-cleanup snapshots
    precleanup_snapshots = service_client.describe_snapshots(
        Filters = [{
            'Name': 'tag:Name',
            'Values': [
                snapshot_id
            ]
        }]
    )

    #Assert Snapshot(s) exist
    self.assertTrue(len(precleanup_snapshots['Snapshots']) ==1)

    #Create snapshot id
    snap_id = precleanup_snapshots['Snapshots'][0]['SnapshotId']
    
    #Set cleanup date
    service_client.create_tags(
            Resources=[snap_id],
            Tags=[{'Key': f"{RuntimeConfig.get_tag_prefix()}:date_created",
                    'Value': datetime(1990, 1, 1).strftime(BackupResource.TIMESTAMP_FORMAT)
                    }]
        )

    backup_engine.clean_backups()

    #Get Snapshots after cleanup
    postcleanup_snapshots = service_client.describe_snapshots(
        Filters = [{
            'Name': 'tag:Name',
            'Values': [
                snapshot_id
            ]
        }]
    )

    #Snapshot after cleanup
    print("Post-Cleanup Snapshots: " + str(postcleanup_snapshots))

    #Ensure cleanup removed all snapshots
    self.assertTrue(len(postcleanup_snapshots['Snapshots']) == 0)

    return True

def ec2_cleanup_backups(self,backup,backup_engine,service_client):
    snapshot_id = backup.name
      
    #Get pre-cleanup snapshots
    precleanup_snapshots = service_client.describe_snapshots(
        Filters = [{
            'Name': 'tag:Name',
            'Values': [
                snapshot_id
            ]
        }]
    )

    #Assert Snapshot(s) exist
    self.assertTrue(len(precleanup_snapshots['Snapshots']) ==1)

    tags= precleanup_snapshots['Snapshots'][0]['Tags']

    ami_id = [tag['Value'] for tag in tags if tag['Key'] == 'shelvery:ami_id'][0]

    #Create snapshot id
    snap_id = precleanup_snapshots['Snapshots'][0]['SnapshotId']
    
    #Set cleanup date
    service_client.create_tags(
            Resources=[snap_id,ami_id],
            Tags=[{'Key': f"{RuntimeConfig.get_tag_prefix()}:date_created",
                    'Value': datetime(1990, 1, 1).strftime(BackupResource.TIMESTAMP_FORMAT)
                    }]
        )

    backup_engine.clean_backups()

    #Get Snapshots after cleanup
    postcleanup_snapshots = service_client.describe_snapshots(
        Filters = [{
            'Name': 'tag:Name',
            'Values': [
                snapshot_id
            ]
        }]
    )

    #Snapshot after cleanup
    print("Post-Cleanup Snapshots: " + str(postcleanup_snapshots))

    #Ensure cleanup removed all snapshots
    self.assertTrue(len(postcleanup_snapshots['Snapshots']) == 0)

    return True
   
def ebs_pull_backups(self, service_client, backup_engine, db_identifier):
     
    cleanEC2Snapshots()

    #Set environment variables
    source_aws_id = source_account
    os.environ["shelvery_source_aws_account_ids"] = str(source_aws_id)

    print("Pulling shared backups")
    backup_engine.pull_shared_backups()

    #Get owned snapshots
    owned_snapshots = service_client.describe_snapshots( 
        OwnerIds=[
        destination_account,
        ] 
    )['Snapshots']   

    print("Owned Snapshots: " + str(owned_snapshots))

    pulled_snapshots = []

    #Retrieve all snapshots with 'shelvery-test-ebs' in tags
    for snapshot in owned_snapshots:
        if 'Tags' in snapshot:
            tags = snapshot['Tags']
            name = [tag['Value'] for tag in tags if tag['Key'] == 'Name'][0]

            if 'shelvery-test-ebs' in name:
                pulled_snapshots.append(snapshot)

    #Assert 1 image has been pulled
    print(pulled_snapshots)
    self.assertTrue(len(pulled_snapshots) == 1)

def ec2_pull_backups(self, service_client, backup_engine):

    cleanEC2Snapshots()

     #Set environment variables
    source_aws_id = source_account
    os.environ["shelvery_source_aws_account_ids"] = str(source_aws_id)

    backup_engine.pull_shared_backups()

    search_filter = [{'Name':'tag:ResourceName',
                      'Values':['shelvery-test-ec2']
                    }]
                                  
    #Retrieve pulled images from shelvery-test stack
    amis = service_client.describe_images(
                    Filters=search_filter
                )['Images']
    
    print("AMI's: " + str(amis))

    #Ensure 1 image has been pulled
    self.assertTrue(len(amis) == 1)

