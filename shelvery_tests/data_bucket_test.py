from http.client import responses
from inspect import stack
import json
from select import POLLHUP
import unittest
import boto3
import pytest
import os
from shelvery.engine import ShelveryEngine
from shelvery.aws_helper import AwsHelper
from shelvery_tests.conftest import destination_account


class DataBucketIntegrationTestCase(unittest.TestCase):
    """Data Bucket  Integration shelvery tests"""


    @pytest.mark.source
    @pytest.mark.share
    def test_CreateDataBucket(self):

        s3client = AwsHelper.boto3_client('s3', region_name='ap-southeast-2')
        sts = AwsHelper.boto3_client('sts')
        id = str(sts.get_caller_identity()['Account'])
        os.environ['SHELVERY_MONO_THREAD'] = '1'

        share_with_id = destination_account
        os.environ["shelvery_share_aws_account_ids"] = str(share_with_id)

        engine = ShelveryEngine()

        print("Creating Data Buckets")
        engine.create_data_buckets()

        bucket_name = f"shelvery.data.{id}-ap-southeast-2.base2tools"

        response = s3client.get_bucket_policy(
            Bucket=bucket_name
        )['Policy']

        policy = json.loads(response)['Statement']

        print("Policy: " + str(policy))

        valid = False

        #Add other checks on policy?

        for statement in policy:
            if statement['Effect'] == "Allow" and str(share_with_id) in statement['Principal']['AWS']:
                valid = True

        self.assertTrue(valid)




