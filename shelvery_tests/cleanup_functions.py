from shelvery.aws_helper import AwsHelper
from shelvery_tests.resources import DOCDB_RESOURCE_NAME, RDS_INSTANCE_RESOURCE_NAME,RDS_CLUSTER_RESOURCE_NAME, EC2_AMI_INSTANCE_RESOURCE_NAME, EBS_INSTANCE_RESOURCE_NAME
from shelvery_tests.docdb_integration_test import DocDBTestClass
from shelvery_tests.ebs_integration_test import EBSTestClass
from shelvery_tests.ec2ami_integration_test import EC2AmiTestClass
from shelvery_tests.rds_cluster_integration_test import RDSClusterTestClass
from shelvery_tests.rds_integration_test import RDSInstanceTestClass

def cleanDocDBSnapshots():
    print("Cleaning up DocDB Snapshots")
    docdb_test_class = DocDBTestClass()
    backups_engine = docdb_test_class.backups_engine
    # Clean backups
    backups_engine.clean_backups()
    
    # client = AwsHelper.boto3_client('docdb', region_name='ap-southeast-2')

    # snapshots = client.describe_db_cluster_snapshots(
    #     DBClusterIdentifier=DOCDB_RESOURCE_NAME,
    #     SnapshotType='Manual'
    # )['DBClusterSnapshots']

    # for snapshot in snapshots:
    #     snapid = snapshot['DBClusterSnapshotIdentifier']
    #     try:
    #         print(f"Deleting snapshot: {snapid}")
    #         client.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snapid)
    #     except Exception as e:
    #         print(f"Failed to delete {snapid}:{str(e)}")

def cleanRdsClusterSnapshots():
    print("Cleaning up RDS Cluster Snapshots")
    rds_cluster_test_class = RDSClusterTestClass()
    backups_engine = rds_cluster_test_class.backups_engine
    # Clean backups
    backups_engine.clean_backups()
    
    # rdsclusterclient = AwsHelper.boto3_client('rds', region_name='ap-southeast-2')

    # snapshots =  rdsclusterclient.describe_db_cluster_snapshots(
    #     DBClusterIdentifier=RDS_CLUSTER_RESOURCE_NAME,
    #     SnapshotType='Manual'
    # )['DBClusterSnapshots']

    # for snapshot in snapshots:
    #     snapid = snapshot['DBClusterSnapshotIdentifier']

    #     try:
    #         print(f"Deleting snapshot: {snapid}")
    #         rdsclusterclient.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snapid)
    #     except Exception as e:
    #         print(f"Failed to delete {snapid}:{str(e)}")

def cleanRdsSnapshots():
    print("Cleaning up RDS Snapshots")
    rds_instance_test_class = RDSInstanceTestClass()
    backups_engine = rds_instance_test_class.backups_engine
    # Clean backups
    backups_engine.clean_backups()
    
    # rdsclient = AwsHelper.boto3_client('rds', region_name='ap-southeast-2')
     
    # snapshots = rdsclient.describe_db_snapshots(
    #     DBInstanceIdentifier=RDS_INSTANCE_RESOURCE_NAME,
    #     SnapshotType='Manual',
    # )['DBSnapshots']
          
    # for snapshot in snapshots:
    #     snapid = snapshot['DBSnapshotIdentifier']

    #     try:
    #         print(f"Deleting snapshot: {snapid}")
    #         rdsclient.delete_db_snapshot(DBSnapshotIdentifier=snapid)
    #     except Exception as e:
    #         print(f"Failed to delete {snapid}:{str(e)}")

def cleanEC2Snapshots():
    print("Cleaning up EC2 AMI Snapshots")
    ec2_ami_test_class = EC2AmiTestClass()
    backups_engine = ec2_ami_test_class.backups_engine
    # Clean backups
    backups_engine.clean_backups()
    
    # ec2client = AwsHelper.boto3_client('ec2', region_name='ap-southeast-2')
    # sts = AwsHelper.boto3_client('sts')
    # id = str(sts.get_caller_identity()['Account'])

    # snapshots = ec2client.describe_snapshots(
    #     OwnerIds=[id] 
    # )['Snapshots']

    # for snapshot in snapshots:
    #     snapid = snapshot['SnapshotId']
    #     if 'Tags' in snapshot:
    #         tags = snapshot['Tags']
    #         try:
    #             name = [tag['Value'] for tag in tags if tag['Key'] == 'Name'][0]
    #             if EC2_AMI_INSTANCE_RESOURCE_NAME in name:
    #                 print("Cleaning up EC2 AMI Snapshots")
    #                 ami_id = [tag['Value'] for tag in tags if tag['Key'] == 'shelvery:ami_id'][0]
    #                 if ami_id != []:
    #                     print(f"De-registering image: {ami_id}")
    #                     ec2client.deregister_image(ImageId=ami_id)
    #                 ec2client.delete_snapshot(SnapshotId=snapid)
    #                 print(f'Deleting EC2 snapshot: {snapid}')
    #             if EBS_INSTANCE_RESOURCE_NAME in name:
    #                 print("Cleaning up EBS Snapshots")
    #                 print(f'Deleting EBS snapshot: {snapid}')
    #                 ec2client.delete_snapshot(SnapshotId=snapid)
    #         except Exception as e:
    #             print(f"Failed to delete {snapid}:{str(e)}")
        
    #     else:
    #        print(f'Deleting Untagged EC2 Snapshots')
    #        if snapshot['VolumeId'] == 'vol-ffffffff' and 'Copied for' in snapshot['Description']:

    #             search_filter = [{'Name':'block-device-mapping.snapshot-id',
    #                               'Values': [snapid],
    #                               'Name':'tag:ResourceName',
    #                               'Values':[EC2_AMI_INSTANCE_RESOURCE_NAME]
    #                             }]
                                  
                        

    #             ami_id = ec2client.describe_images(
    #                 Filters=search_filter
    #             )['Images'][0]['ImageId']
    #             try:
    #                 print(f"De-registering image: {ami_id}")
    #                 print(f'Deleting EC2 snapshot: {snapid}')
    #                 ec2client.deregister_image(ImageId=ami_id)
    #                 ec2client.delete_snapshot(SnapshotId=snapid)
    #             except Exception as e:
    #                 print(f"Failed to delete {snapid}:{str(e)}")

def cleanEBSSnapshots():
    print("Cleaning up EBS Snapshots")
    # Create test resource class
    ebs_test_class = EBSTestClass()
    backups_engine = ebs_test_class.backups_engine
    # Clean backups
    backups_engine.clean_backups()

def cleanupSnapshots():
    cleanDocDBSnapshots()
    cleanEC2Snapshots()
    cleanEBSSnapshots()
    cleanRdsClusterSnapshots()
    cleanRdsSnapshots()
                