import logging
import json

from shelvery.factory import ShelveryFactory

def lambda_handler(event, context):

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.info(f"Received event\n{json.dumps(event,indent=2)}")

    # handle both sns and cloudwatch secheduled events
    if 'Records' in event:
        payload = json.loads(event['Records'][0]['Sns']['Message'])
    else:
        payload = event

    if 'backup_type' not in payload:
        raise Exception("Expecting backup type in event payload in \"backup_type\" key")

    if 'action' not in payload:
        raise Exception("Expecting backup action in event payload in \"action\" key")

    backup_type = payload['backup_type']
    action = payload['action']

    # create backup engine
    backup_engine = ShelveryFactory.get_shelvery_instance(backup_type)
    backup_engine.set_lambda_environment(payload, context)

    method = backup_engine.__getattribute__(action)

    if 'arguments' in payload:
        method(event['arguments'])
    else:
        method()

    return 0
