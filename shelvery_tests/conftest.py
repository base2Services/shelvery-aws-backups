import pytest
import boto3
import os
import time
from shelvery.aws_helper import AwsHelper
from botocore.exceptions import ClientError

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

        #Need to add perms for describestack?

        stacks = cfclient.describe_stacks()

        #Check whether stack aleady exists
        test_stack = [stack for stack in stacks['Stacks'] if stack['StackName'] == 'shelvery-test']
        
        if len(test_stack) > 0:
            shelvery_status = cfclient.describe_stacks(StackName='shelvery-test')['Stacks'][0]['StackStatus']

            if shelvery_status == 'CREATE_COMPLETE':
                cfclient.delete_stack(
                    StackName='shelvery-test',
                    )
                shelvery_status = cfclient.describe_stacks(StackName='shelvery-test')['Stacks'][0]['StackStatus']

            while shelvery_status == 'DELETE_IN_PROGRESS' or shelvery_status == 'DELETE_COMPLETE':
                print("Waiting for stack to teardown")
                time.sleep(30)

                try:
                    shelvery_status = cfclient.describe_stacks(StackName='shelvery-test')['Stacks'][0]['StackStatus']
                except ClientError as error:
                    if error.response["Error"]["Code"] == "ValidationError":
                        shelvery_status = "DELETED"
                        
            

        # Create stack from template
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

        #Wait till stack is created
        while shelvery_status != 'CREATE_COMPLETE':
            print("Creating Stack...")
            time.sleep(30)
            shelvery_status = cfclient.describe_stacks(StackName='shelvery-test')['Stacks'][0]['StackStatus']

        print('STACK CREATED')
        
        #Cleanup snapshots after stack is created
        cleanupSnapshots()

        # def teardown():
        #     print ("Initiating Teardown")
        #     response = cfclient.delete_stack(
        #         StackName='shelvery-test',
        #         )
        
        # request.addfinalizer(teardown)

    #Cleanup snapshots in destination account
    else:
        cleanupSnapshots()

        # def teardown():
        #     cleanupSnapshots()
        
        # request.addfinalizer(teardown)
