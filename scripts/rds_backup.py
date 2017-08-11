#!/usr/bin/env python
import importlib
import sys
import os

if 'PWD' in os.environ:
    pwd = os.environ['PWD']
elif 'LAMBDA_TASK_ROOT' in os.environ:
    pwd = os.environ['LAMBDA_TASK_ROOT']
else:
    pwd = "."

sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.rds_backup import ShelveryRDSBackup

def entrypoint():
    ebs_backup = ShelveryRDSBackup()
    ebs_backup.create_backups()

entrypoint()
