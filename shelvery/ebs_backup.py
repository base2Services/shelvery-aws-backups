from typing import List

from shelvery.ec2_backup import ShelveryEC2Backup
from shelvery.entity_resource import EntityResource
from shelvery.backup_resource import BackupResource


class ShelveryEBSBackup(ShelveryEC2Backup):
    """Shelvery engine implementation for EBS data backups"""
    
    def __init__(self):
        ShelveryEC2Backup.__init__(self)
    
    def delete_backup(self, backup_resource: BackupResource):
        self.ec2client.delete_snapshot(SnapshotId=backup_resource.backup_id)
    
    def get_existing_backups(self, tag_prefix: str) -> List[BackupResource]:
        # lookup snapshots by tags
        snapshots = self.ec2client.describe_snapshots(Filters=[
            {'Name': f"tag:{tag_prefix}:{BackupResource.BACKUP_MARKER_TAG}", 'Values': ['true']}
        ])
        backups = []
        
        # create backup resource objects
        for snap in snapshots['Snapshots']:
            backup = BackupResource.construct(
                tag_prefix=tag_prefix,
                backup_id=snap['SnapshotId'],
                tags=dict(map(lambda t: (t['Key'], t['Value']), snap['Tags']))
            )
            backups.append(backup)
        
        return backups
    
    def get_resource_type(self) -> str:
        return 'ec2 volume'
    
    def backup_resource(self, backup_resource: BackupResource) -> BackupResource:
        # create snapshot
        snap = self.ec2client.create_snapshot(
            VolumeId=backup_resource.entity_id,
            Description=backup_resource.name
        )
        backup_resource.backup_id = snap['SnapshotId']
        return backup_resource
    
    def get_entities_to_backup(self, tag_name: str) -> List[EntityResource]:
        volumes = self.collect_volumes(tag_name)
        print(volumes)
        return list(
            map(
                lambda vol: EntityResource(
                    resource_id=vol['VolumeId'],
                    date_created=vol['CreateTime'],
                    tags=dict(map(lambda t: (t['Key'], t['Value']), vol['Tags']))
                ),
                volumes
            )
        )
    
    # collect all volumes tagged with given tag, in paginated manner
    def collect_volumes(self, tag_name: str):
        load_volumes = True
        next_token = ''
        all_volumes = []
        while load_volumes:
            tagged_volumes = self.ec2client.describe_volumes(
                Filters=[{'Name': "tag-key", 'Values': [tag_name]}],
                NextToken=next_token
            )
            all_volumes = all_volumes + tagged_volumes['Volumes']
            if 'NextToken' in tagged_volumes and len(tagged_volumes['NextToken']) > 0:
                load_volumes = True
                next_token = tagged_volumes['NextToken']
            else:
                load_volumes = False
        
        return all_volumes
