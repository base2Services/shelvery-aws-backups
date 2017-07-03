from shelvery.ebs_backup import ShelveryEBSBackup
from shelvery.engine import ShelveryEngine


class ShelveryFactory:
    
    @classmethod
    def get_shelvery_instance(cls, type: str) -> ShelveryEngine:
        if type == 'ebs':
            return ShelveryEBSBackup()
        
        if type == 'rds':
            raise Exception("RDS Not supported yet")
        
        if type == 'ami':
            raise Exception("AMIs not supported yet")