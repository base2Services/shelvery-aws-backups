import pytest
import boto3
import os
import time
from shelvery.aws_helper import AwsHelper

from shelvery_tests.cleanup_functions import cleanupSnapshots

source_account = None
destination_account = None

def pytest_addoption(parser):
    parser.addoption("--destination", action="store", default="None")
    parser.addoption("--source", action="store", default="None")


def pytest_configure(config):
    global source_account
    global destination_account
    
    source_account = config.getoption('--source')
    destination_account = config.getoption('--destination')

#Add some check here on if the stack aleady exists (eg: deleting/creating/available)
        
@pytest.fixture(scope="session", autouse=True)
def setup(request):

    sts = AwsHelper.boto3_client('sts')
    id = str(sts.get_caller_identity()['Account'])

    if id == source_account:

        cfclient = boto3.client('cloudformation')
        cwd = os.getcwd()
        template_path = f"{cwd}/cloudformation-unittest.yaml"

        template = ""
        with open(template_path, "r") as file:
            template = file.read()

        create_response = cfclient.create_stack(
            StackName='shelvery-test',
            TemplateBody=template
            
        )

        shelvery_status = ""

        while shelvery_status != 'CREATE_COMPLETE':
            print("Creating Stack...")
            time.sleep(30)
            shelvery_status = cfclient.describe_stacks(StackName='shelvery-test' )['Stacks'][0]['StackStatus']

        print('STACK CREATED')
        
        cleanupSnapshots()

        def teardown():
            print ("Initiating Teardown")
            response = cfclient.delete_stack(
                StackName='shelvery-test',
                )
        
        request.addfinalizer(teardown)

    else:
        cleanupSnapshots()