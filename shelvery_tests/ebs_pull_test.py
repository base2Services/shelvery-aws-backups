import sys
import unittest
import os
import pytest
from shelvery_tests.ebs_integration_test import EBSTestClass
from shelvery_tests.test_functions import setup_destination
from shelvery_tests.resources import EBS_INSTANCE_RESOURCE_NAME


pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

class ShelveryEBSPullTestCase(unittest.TestCase):
    
    @pytest.mark.destination
    def test_PullEBSBackup(self):

        # Complete initial setup
        print(f"EBS - Running pull shared backups test")
        setup_destination(self)
    
        # Create test resource class
        ebs_test_class = EBSTestClass()
        backups_engine = ebs_test_class.backups_engine
        client = ebs_test_class.client
        
        # Clean residual existing snapshots
        backups_engine.clean_backups()

        search_filter = [{'Name':'tag:ResourceName',
                        'Values':[EBS_INSTANCE_RESOURCE_NAME]
                        }]

        # Snapshot count before pull (may include non-stale leftovers from prior runs)
        pre_pull_count = len(client.describe_snapshots(
                        Filters=search_filter
                    )['Snapshots'])

        # Pull shared backups
        backups_engine.pull_shared_backups()

        snapshots = client.describe_snapshots(
                        Filters=search_filter
                    )['Snapshots']

        pulled_count = len(snapshots) - pre_pull_count
        self.assertGreaterEqual(pulled_count, 1, f"Expected at least 1 new snapshot from pull, but got {pulled_count}")
    
    @pytest.mark.cleanup
    def test_cleanup(self):
        # Create test resource class
        ebs_test_class = EBSTestClass()
        backups_engine = ebs_test_class.backups_engine
         # Clean backups
        backups_engine.clean_backups()
