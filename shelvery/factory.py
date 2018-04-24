from shelvery.ebs_backup import ShelveryEBSBackup
from shelvery.engine import ShelveryEngine
from shelvery.rds_backup import  ShelveryRDSBackup
from shelvery.rds_cluster_backup import ShelveryRDSClusterBackup
from shelvery.ec2ami_backup import ShelveryEC2AMIBackup

class ShelveryFactory:

    @classmethod
    def get_shelvery_instance(cls, type: str) -> ShelveryEngine:
        if type == 'ebs':
            return ShelveryEBSBackup()

        if type == 'rds':
            return ShelveryRDSBackup()

        if type == 'rds_cluster':
            return ShelveryRDSClusterBackup()

        if type == 'ec2ami':
            return ShelveryEC2AMIBackup()