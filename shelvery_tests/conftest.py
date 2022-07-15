import pytest
import boto3
import os
import time
from shelvery.aws_helper import AwsHelper

from shelvery_tests.test_functions import cleanupSnapshots

@pytest.fixture(scope="session", autouse=True)
def setup(request):

    sts = AwsHelper.boto3_client('sts')
    id = str(sts.get_caller_identity()['Account'])

    if id == '988966687271':

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
