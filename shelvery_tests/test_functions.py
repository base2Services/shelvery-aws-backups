#Functions used to compare snapshots/clusters/instances 
from datetime import datetime
from turtle import back
from warnings import filters
from xml.dom import pulldom
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
import pytest
from shelvery_tests.conftest import destination_account, source_account
from shelvery_tests.cleanup_functions import cleanEC2Snapshots
# Compare backup cluster with aws cluster

# Compare rds snap with backup snap etc

def addBackupTags(client,resource_name,tag_value):
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

def initSetup(self,service_name):
    print(f"Setting up {service_name} integration test")
    os.environ['AWS_DEFAULT_REGION'] = 'ap-southeast-2'
    os.environ['SHELVERY_MONO_THREAD'] = '1'
    
    sts = AwsHelper.boto3_client('sts')
    self.id = sts.get_caller_identity()
    print(f"Running as user:\n{self.id}\n")

def initCreateBackups(backup_engine):
    try:
        backups = backup_engine.create_backups()
    except Exception as e:
        print(e)
        print(f"Failed with {e}")
        traceback.print_exc(file=sys.stdout)
        raise e

    return backups

def initShareBackups(backup_engine, share_with_id):
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

def initCleanup(backup_engine):
    try:
        backups = backup_engine.create_backups()
    except Exception as e:
        print(e)
        print(f"Failed with {e}")
        traceback.print_exc(file=sys.stdout)
        raise e        

    return backups

def compareBackups(self,backup,backup_engine):
    print("Inside backup loop" + backup.backup_id)
    snapshot_id = backup.backup_id
    self.created_snapshots.append(snapshot_id)

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
    
    return True

def clusterShareBackups(self, backup, service):
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

    restore_attribute = [attr for attr in attributes if attr['AttributeName'] == 'restore'][0]['AttributeValues']

    #Assert Snapshot(s) exist
    self.assertTrue(len(source_snapshot['DBClusterSnapshots']) ==1)

    #Assert that snapshot is shared with dest account
    self.assertTrue(destination_account in restore_attribute)

    return True

def clusterCleanupBackups(self, backup, backup_engine, resource_client):
    snapshot_id = backup.backup_id
      
    #Get source snapshot
    source_snapshot = resource_client.describe_db_cluster_snapshots(
        DBClusterIdentifier=backup.entity_id,
        DBClusterSnapshotIdentifier=snapshot_id
    )

    #Assert Snapshot(s) exist
    self.assertTrue(len(source_snapshot['DBClusterSnapshots']) ==1)

    snapshot_arn = source_snapshot['DBClusterSnapshots'][0]['DBClusterSnapshotArn']

    #Set cleanup date
    resource_client.add_tags_to_resource(
            ResourceName=snapshot_arn,
            Tags=[{'Key': f"{RuntimeConfig.get_tag_prefix()}:date_created",
                    'Value': datetime(1990, 1, 1).strftime(BackupResource.TIMESTAMP_FORMAT)
                    }]
        )

    backup_engine.clean_backups()

    sourcepost_snapshot = resource_client.describe_db_cluster_snapshots(
        DBClusterIdentifier=backup.entity_id,
        DBClusterSnapshotIdentifier=snapshot_id
    )

    #Ensure cleanup removed all snapshots
    self.assertTrue(len(sourcepost_snapshot['DBClusterSnapshots']) == 0)

    return True

def instanceShareBackups(self,backup):
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

    restore_attribute = [attr for attr in attributes if attr['AttributeName'] == 'restore'][0]['AttributeValues']
    
    #Assert Snapshot(s) exist
    self.assertTrue(len(source_snapshot['DBSnapshots']) ==1)

    #Assert that snapshot is shared with dest account
    self.assertTrue(destination_account in restore_attribute)

    return True

def instanceCleanupBackups(self,backup,backup_engine,service_client):
    snapshot_id = backup.backup_id
      
    #Get source snapshot
    source_snapshot = service_client.describe_db_snapshots(
        DBInstanceIdentifier=backup.entity_id,
        DBSnapshotIdentifier=snapshot_id
    )

    #Assert Snapshot(s) exist
    self.assertTrue(len(source_snapshot['DBSnapshots']) ==1)

    sourcepost_snapshot = service_client.describe_db_snapshots(
        DBInstanceIdentifier=backup.entity_id,
        DBSnapshotIdentifier=snapshot_id
    )

    snapshot_arn = source_snapshot['DBSnapshots'][0]['DBSnapshotArn']
    
    #Set cleanup date
    service_client.add_tags_to_resource(
            ResourceName=snapshot_arn,
            Tags=[{'Key': f"{RuntimeConfig.get_tag_prefix()}:date_created",
                    'Value': datetime(1990, 1, 1).strftime(BackupResource.TIMESTAMP_FORMAT)
                    }]
        )

    backup_engine.clean_backups()

    sourcepost_snapshot = service_client.describe_db_snapshots(
        DBInstanceIdentifier=backup.entity_id,
        DBSnapshotIdentifier=snapshot_id
    )

    print("POSTOPS")
    print(sourcepost_snapshot)

    #Ensure cleanup removed all snapshots
    self.assertTrue(len(sourcepost_snapshot['DBSnapshots']) == 0)

    return True

def ec2ShareBackups(self,backup):
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

    restore_attributes = [attr for attr in attributes if attr['UserId'] == destination_account]

    #Assert Snapshot(s) exist
    self.assertTrue(len(source_snapshot['Snapshots']) ==1)

     #Assert that snapshot is shared with dest account
    self.assertTrue(len(restore_attributes) == 1)

    return True

def ebsCleanupBackups(self,backup,backup_engine,service_client):
    snapshot_id = backup.name
      
    #Get source snapshot
    source_snapshot = service_client.describe_snapshots(
        Filters = [{
            'Name': 'tag:Name',
            'Values': [
                snapshot_id
            ]
        }]
    )

    #Assert Snapshot(s) exist
    self.assertTrue(len(source_snapshot['Snapshots']) ==1)

    tags= source_snapshot['Snapshots'][0]['Tags']

    #Create snapshot id
    snap_id = source_snapshot['Snapshots'][0]['SnapshotId']
    
    #Set cleanup date
    service_client.create_tags(
            Resources=[snap_id],
            Tags=[{'Key': f"{RuntimeConfig.get_tag_prefix()}:date_created",
                    'Value': datetime(1990, 1, 1).strftime(BackupResource.TIMESTAMP_FORMAT)
                    }]
        )

    backup_engine.clean_backups()

    after_snapshot = service_client.describe_snapshots(
        Filters = [{
            'Name': 'tag:Name',
            'Values': [
                snapshot_id
            ]
        }]
    )

    print("AFTER")
    print(after_snapshot)


    #Ensure cleanup removed all snapshots
    self.assertTrue(len(after_snapshot['Snapshots']) == 0)

    return True

def ec2CleanupBackups(self,backup,backup_engine,service_client):
    snapshot_id = backup.name
      
    #Get source snapshot
    source_snapshot = service_client.describe_snapshots(
        Filters = [{
            'Name': 'tag:Name',
            'Values': [
                snapshot_id
            ]
        }]
    )

    #Assert Snapshot(s) exist
    self.assertTrue(len(source_snapshot['Snapshots']) ==1)

    tags= source_snapshot['Snapshots'][0]['Tags']

    ami_id = [tag['Value'] for tag in tags if tag['Key'] == 'shelvery:ami_id'][0]

    #Create snapshot id
    snap_id = source_snapshot['Snapshots'][0]['SnapshotId']
    
    ### TAG AMI!

    print("BEFORE")
    print(source_snapshot)

    #Set cleanup date
    service_client.create_tags(
            Resources=[snap_id,ami_id],
            Tags=[{'Key': f"{RuntimeConfig.get_tag_prefix()}:date_created",
                    'Value': datetime(1990, 1, 1).strftime(BackupResource.TIMESTAMP_FORMAT)
                    }]
        )

    backup_engine.clean_backups()

    after_snapshot = service_client.describe_snapshots(
        Filters = [{
            'Name': 'tag:Name',
            'Values': [
                snapshot_id
            ]
        }]
    )

    print("AFTER")
    print(after_snapshot)


    #Ensure cleanup removed all snapshots
    self.assertTrue(len(after_snapshot['Snapshots']) == 0)

    return True
   
def ebsPullBackups(self, service_client, backup_engine, db_identifier):
     
    cleanEC2Snapshots()

    source_aws_id = source_account
    os.environ["shelvery_source_aws_account_ids"] = str(source_aws_id)

    print("Pulling shared backups")
    backup_engine.pull_shared_backups()

    owned_snapshots = service_client.describe_snapshots( 
        OwnerIds=[
        destination_account,
        ] 
    )['Snapshots']   

    pulled_snapshots = []

    for snapshot in owned_snapshots:

        if 'Tags' in snapshot:
            tags = snapshot['Tags']
            name = [tag['Value'] for tag in tags if tag['Key'] == 'Name'][0]

            if 'shelvery-test-ebs' in name:
                pulled_snapshots.append(snapshot)

    print(pulled_snapshots)
    self.assertTrue(len(pulled_snapshots) == 1)


def ec2PullBackups(self, service_client, backup_engine):

    cleanEC2Snapshots()

    source_aws_id = source_account
    os.environ["shelvery_source_aws_account_ids"] = str(source_aws_id)
     
    snapshots =  service_client.describe_snapshots(
        OwnerIds=[
        source_account,
        ]   
    )['Snapshots']

    snapshot_ids = [snapshot['SnapshotId'] for snapshot in snapshots if 'Created by CreateImage' in snapshot['Description']]

    print("Pulling shared backups")
    backup_engine.pull_shared_backups()

    owned_snapshots = service_client.describe_snapshots( 
        OwnerIds=[
        destination_account,
        ] 
    )['Snapshots']   

    pulled_snapshots = []
    
    for snapshot_id in snapshot_ids:
        pulled_snapshots += [snapshot for snapshot in owned_snapshots if snapshot_id in snapshot['Description']]

    print("EC2 PULLED SNAPS:" + str(pulled_snapshots))
    
    self.assertTrue(len(pulled_snapshots) == 1)

