from shelvery.aws_helper import AwsHelper

def cleanDocDBSnapshots():
    docdbclient = AwsHelper.boto3_client('docdb', region_name='ap-southeast-2')

    snapshots = docdbclient.describe_db_cluster_snapshots(
        DBClusterIdentifier='shelvery-test-docdb',
        SnapshotType='Manual'
    )['DBClusterSnapshots']

    for snapshot in snapshots:
        snapid = snapshot['DBClusterSnapshotIdentifier']

        try:
            docdbclient.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snapid)
        except Exception as e:
            print(f"Failed to delete {snapid}:{str(e)}")

def cleanRdsClusterSnapshots():
    rdsclusterclient = AwsHelper.boto3_client('rds', region_name='ap-southeast-2')

    snapshots =  rdsclusterclient.describe_db_cluster_snapshots(
        DBClusterIdentifier='shelvery-test-rds-cluster',
        SnapshotType='Manual'
    )['DBClusterSnapshots']

    for snapshot in snapshots:
        snapid = snapshot['DBClusterSnapshotIdentifier']

        try:
            rdsclusterclient.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snapid)
        except Exception as e:
            print(f"Failed to delete {snapid}:{str(e)}")

def cleanRdsSnapshots():
    rdsclient = AwsHelper.boto3_client('rds', region_name='ap-southeast-2')
     
    snapshots = rdsclient.describe_db_snapshots(
        DBInstanceIdentifier='shelvery-test-rds',
        SnapshotType='Manual',
    )['DBSnapshots']
          
    for snapshot in snapshots:
        snapid = snapshot['DBSnapshotIdentifier']

        try:
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
                    ami_id = [tag['Value'] for tag in tags if tag['Key'] == 'shelvery:ami_id'][0]
                    if ami_id != []:
                        ec2client.deregister_image(ImageId=ami_id)
                    ec2client.delete_snapshot(SnapshotId=snapid)
                if 'shelvery-test-ebs' in name:
                    ec2client.delete_snapshot(SnapshotId=snapid)
            except Exception as e:
                print(f"Failed to delete {snapid}:{str(e)}")
        
        else:
           if snapshot['VolumeId'] == 'vol-ffffffff' and 'Copied for' in snapshot['Description']:

                search_filter = [{'Name':'block-device-mapping.snapshot-id',
                                  'Values': [snapid],
                                  'Name':'tag:ResourceName',
                                  'Values':['shelvery-test-ec2']
                                }]
                                  
                        

                ami_id = ec2client.describe_images(
                    Filters=search_filter
                )['Images'][0]['ImageId']
                ec2client.deregister_image(ImageId=ami_id)
                ec2client.delete_snapshot(SnapshotId=snapid)

def cleanupSnapshots():
    cleanDocDBSnapshots()
    cleanEC2Snapshots()
    cleanRdsClusterSnapshots()
    cleanRdsSnapshots()
                