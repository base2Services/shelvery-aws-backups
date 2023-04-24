from shelvery.documentdb_backup import ShelveryDocumentDbBackup
from shelvery.ebs_backup import ShelveryEBSBackup
from shelvery.ec2ami_backup import ShelveryEC2AMIBackup
from shelvery.rds_cluster_backup import ShelveryRDSClusterBackup
from shelvery.rds_backup import ShelveryRDSBackup
from shelvery.aws_helper import AwsHelper
import boto3
import os

def cleanDocDBSnapshots():
    print("Cleaning up DocDB Snapshots")
    backups_engine = ShelveryDocumentDbBackup()
    backups_engine.clean_backups()
    
def cleanRdsClusterSnapshots():
    print("Cleaning up RDS Cluster Snapshots")
    backups_engine = ShelveryRDSClusterBackup()
    backups_engine.clean_backups()

def cleanRdsSnapshots():
    print("Cleaning up RDS Snapshots")
    backups_engine = ShelveryRDSBackup()
    backups_engine.clean_backups()

def cleanEC2Snapshots():
    print("Cleaning up EC2 AMI Snapshots")
    backups_engine = ShelveryEC2AMIBackup()
    backups_engine.clean_backups()
  
def cleanEBSSnapshots():
    print("Cleaning up EBS Snapshots")
    backups_engine = ShelveryEBSBackup()
    backups_engine.clean_backups()
    
def cleanS3Bucket():
    print("Cleaning S3 Bucket")
    bucket_name = f"shelvery.data.{AwsHelper.local_account_id()}-ap-southeast-2.base2tools"
    s3 = boto3.resource('s3')
    bucket = s3.Bucket(bucket_name)

    # Delete all objects in the bucket
    for obj in bucket.objects.all():
        obj.delete()

def cleanupSnapshots():
    os.environ['shelvery_custom_retention_types'] = 'shortLived:1'
    os.environ['shelvery_current_retention_type'] = 'shortLived'
    cleanDocDBSnapshots()
    cleanEC2Snapshots()
    cleanEBSSnapshots()
    cleanRdsClusterSnapshots()
    cleanRdsSnapshots()
                