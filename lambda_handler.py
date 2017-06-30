import os
import sys
import importlib


def lambda_handler(event, context):
    print(os.environ)
    pwd = os.environ['LAMBDA_TASK_ROOT']
    sys.path.append(f"{pwd}/scripts")
    file_name = f"{event['backup_type']}_{event['action']}"
    mymodule = importlib.import_module(file_name)
    mymodule.entrypoint()
    return 0
