import logging
import json

from shelvery.factory import ShelveryFactory

def lambda_handler(event, context):
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.info(f"Received event\n{json.dumps(event,indent=2)}")
    
    if 'backup_type' not in event:
        raise Exception("Expecting backup type in event payload in \"backup_type\" key")

    if 'action' not in event:
        raise Exception("Expecting backup action in event payload in \"action\" key")

    backup_type = event['backup_type']
    action = event['action']

    # create backup engine
    backup_engine = ShelveryFactory.get_shelvery_instance(backup_type)
    backup_engine.set_lambda_environment(event, context)
    
    method = backup_engine.__getattribute__(action)
    
    if 'arguments' in event:
        method(event['arguments'])
    else:
        method()
    
    return 0
