import logging
from shelvery.factory import ShelveryFactory


class ShelveryCliMain:
    
    def main(self, backup_type, action):
    
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        
        # create backup engine
        backup_engine = ShelveryFactory.get_shelvery_instance(backup_type)
        method = backup_engine.__getattribute__(action)
        
        # start the action
        method()
        return 0

