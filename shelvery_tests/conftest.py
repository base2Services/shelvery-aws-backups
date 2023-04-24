import pytest
import boto3
import os
from shelvery.aws_helper import AwsHelper
from botocore.exceptions import ClientError

from shelvery_tests.cleanup_functions import cleanupSnapshots, cleanS3Bucket

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
def create_stack(cfclient):
    create_waiter = cfclient.get_waiter('stack_create_complete')
    cwd = os.getcwd()
    template_path = f"{cwd}/cloudformation-unittest.yaml"

    template = ""
    with open(template_path, "r") as file:
        template = file.read()

    cfclient.create_stack(
        StackName='shelvery-test',
        TemplateBody=template
        
    )

    #Wait till stack is created
    create_waiter.wait(
                StackName='shelvery-test',
                WaiterConfig={
                    'Delay': 30,
                    'MaxAttempts': 50
                     }
            )
    print('STACK CREATED')


@pytest.fixture(scope="session", autouse=True)
def setup(request):

    sts = AwsHelper.boto3_client('sts')
    id = str(sts.get_caller_identity()['Account'])

    if id == source_account:

        #Cleanup any existing snapshots after stack is created
        cleanupSnapshots()
        
        #Cleanup S3 Bucket
        cleanS3Bucket()

        def teardown():
            print ("Initiating Teardown")
            response = cfclient.delete_stack(
                StackName='shelvery-test',
                )
        
        request.addfinalizer(teardown)

        cfclient = boto3.client('cloudformation')
        delete_waiter = cfclient.get_waiter('stack_delete_complete')

        #Get status of stack
        try:
            shelvery_status = cfclient.describe_stacks(StackName='shelvery-test')['Stacks'][0]['StackStatus']
            if shelvery_status == 'DELETE_IN_PROGRESS' or shelvery_status == 'DELETE_COMPLETE':
                #Stack is deleting so wait till deleted
                    delete_waiter.wait(
                        StackName='shelvery-test',
                        WaiterConfig={
                            'Delay': 30,
                            'MaxAttempts': 50
                        }
                    )
                    #Finished deleting stack -> Create new stack
                    create_stack(cfclient=cfclient)

        except ClientError as error:
            if error.response['Error']['Code'] == 'ValidationError':
                #Stack does not exist so create 
                create_stack(cfclient=cfclient)
            else:
                raise error

    #Cleanup snapshots in destination account
    else:
        cleanupSnapshots()

        def teardown():
            cleanupSnapshots()
        
        request.addfinalizer(teardown)
