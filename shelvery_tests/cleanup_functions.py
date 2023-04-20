from shelvery.aws_helper import AwsHelper
from shelvery_tests.resources import DOCDB_RESOURCE_NAME

def cleanDocDBSnapshots():
    print("Cleaning up DocDB Snapshots")

    client = AwsHelper.boto3_client('docdb', region_name='ap-southeast-2')

    snapshots = client.describe_db_cluster_snapshots(
        DBClusterIdentifier=DOCDB_RESOURCE_NAME,
        SnapshotType='Manual'
    )['DBClusterSnapshots']

    for snapshot in snapshots:
        snapid = snapshot['DBClusterSnapshotIdentifier']
        try:
            print(f"Deleting snapshot: {snapid}")
            client.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snapid)
        except Exception as e:
            print(f"Failed to delete {snapid}:{str(e)}")

def cleanRdsClusterSnapshots():
    print("Cleaning up RDS Cluster Snapshots")
    rdsclusterclient = AwsHelper.boto3_client('rds', region_name='ap-southeast-2')

    snapshots =  rdsclusterclient.describe_db_cluster_snapshots(
        DBClusterIdentifier='shelvery-test-rds-cluster',
        SnapshotType='Manual'
    )['DBClusterSnapshots']

    for snapshot in snapshots:
        snapid = snapshot['DBClusterSnapshotIdentifier']

        try:
            print(f"Deleting snapshot: {snapid}")
            rdsclusterclient.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snapid)
        except Exception as e:
            print(f"Failed to delete {snapid}:{str(e)}")

def cleanRdsSnapshots():
    print("Cleaning up RDS Snapshots")
    rdsclient = AwsHelper.boto3_client('rds', region_name='ap-southeast-2')
     
    snapshots = rdsclient.describe_db_snapshots(
        DBInstanceIdentifier='shelvery-test-rds',
        SnapshotType='Manual',
    )['DBSnapshots']
          
    for snapshot in snapshots:
        snapid = snapshot['DBSnapshotIdentifier']

        try:
            print(f"Deleting snapshot: {snapid}")
            rdsclient.delete_db_snapshot(DBSnapshotIdentifier=snapid)
        except Exception as e:
            print(f"Failed to delete {snapid}:{str(e)}")

def cleanEC2Snapshots():
    #EC2 AMI 
    ec2client = AwsHelper.boto3_client('ec2', region_name='ap-southeast-2')
    sts = AwsHelper.boto3_client('sts')
    id = str(sts.get_caller_identity()['Account'])

    snapshots = ec2client.describe_snapshots(
        OwnerIds=[id] 
    )['Snapshots']

    for snapshot in snapshots:
        snapid = snapshot['SnapshotId']
        if 'Tags' in snapshot:
            tags = snapshot['Tags']
            try:
                name = [tag['Value'] for tag in tags if tag['Key'] == 'Name'][0]
                if 'shelvery-test-ec2' in name:
                    print("Cleaning up EC2 AMI Snapshots")
                    ami_id = [tag['Value'] for tag in tags if tag['Key'] == 'shelvery:ami_id'][0]
                    if ami_id != []:
                        print(f"De-registering image: {ami_id}")
                        ec2client.deregister_image(ImageId=ami_id)
                    ec2client.delete_snapshot(SnapshotId=snapid)
                    print(f'Deleting EC2 snapshot: {snapid}')
                if 'shelvery-test-ebs' in name:
                    print("Cleaning up EBS Snapshots")
                    print(f'Deleting EBS snapshot: {snapid}')
                    ec2client.delete_snapshot(SnapshotId=snapid)
            except Exception as e:
                print(f"Failed to delete {snapid}:{str(e)}")
        
        else:
           print(f'Deleting Untagged EC2 Snapshots')
           if snapshot['VolumeId'] == 'vol-ffffffff' and 'Copied for' in snapshot['Description']:

                search_filter = [{'Name':'block-device-mapping.snapshot-id',
                                  'Values': [snapid],
                                  'Name':'tag:ResourceName',
                                  'Values':['shelvery-test-ec2']
                                }]
                                  
                        

                ami_id = ec2client.describe_images(
                    Filters=search_filter
                )['Images'][0]['ImageId']
                try:
                    print(f"De-registering image: {ami_id}")
                    print(f'Deleting EC2 snapshot: {snapid}')
                    ec2client.deregister_image(ImageId=ami_id)
                    ec2client.delete_snapshot(SnapshotId=snapid)
                except Exception as e:
                    print(f"Failed to delete {snapid}:{str(e)}")

def cleanupSnapshots():
    cleanDocDBSnapshots()
    cleanEC2Snapshots()
    cleanRdsClusterSnapshots()
    cleanRdsSnapshots()
                