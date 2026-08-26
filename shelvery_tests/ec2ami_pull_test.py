import sys
import unittest
import os
import pytest
from shelvery_tests.ec2ami_integration_test import EC2AmiTestClass
from shelvery_tests.test_functions import setup_destination, retention_type_filter
from shelvery_tests.resources import EC2_AMI_INSTANCE_RESOURCE_NAME
pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

class ShelveryEC2AmiPullTestCase(unittest.TestCase):
    
    @pytest.mark.destination
    def test_PullEC2Backup(self):
        # Complete initial setup
        print(f"EC2 AMI - Running pull shared backups test")
        setup_destination(self)
    
       # Create test resource class
        ec2_ami_test_class = EC2AmiTestClass()
        backups_engine = ec2_ami_test_class.backups_engine
        client = ec2_ami_test_class.client
        
        # Clean residual existing snapshots
        backups_engine.clean_backups()

        # Pull shared backups
        backups_engine.pull_shared_backups()

        # Get post-pull snapshot count
        # Scoped to this run's retention type. Counting every backup on the resource made
        # the assertion fail against ones left behind by earlier runs, which clean_backups()
        # cannot remove once their retention outlasts the test.
        search_filter = [{'Name':'tag:ResourceName',
                      'Values':[EC2_AMI_INSTANCE_RESOURCE_NAME]
                        },
                        retention_type_filter()]
                                  
        #Retrieve pulled images from shelvery-test stack
        amis = client.describe_images(
                        Filters=search_filter
                    )["Images"]

        # Verify that only one snapshot was pulled
        self.assertEqual(len(amis), 1)

    @pytest.mark.cleanup
    def test_cleanup(self):
        # Create test resource class
        ec2_ami_test_class = EC2AmiTestClass()
        backups_engine = ec2_ami_test_class.backups_engine
         # Clean backups
        backups_engine.clean_backups()
