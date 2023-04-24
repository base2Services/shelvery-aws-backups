import sys
import unittest
import pytest
import os
from shelvery_tests.rds_integration_test import RDSInstanceTestClass
from shelvery_tests.test_functions import setup_destination
from shelvery_tests.resources import RDS_INSTANCE_RESOURCE_NAME

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

class ShelveryRDSPullTestCase(unittest.TestCase):
    
    @pytest.mark.destination
    def test_PullRdsBackup(self):
        
        # Complete initial setup
        print(f"RDS Instance - Running pull shared backups test")
        setup_destination(self)
        
        # Create test resource class
        rds_instance_test_class = RDSInstanceTestClass()
        backups_engine = rds_instance_test_class.backups_engine
        client = rds_instance_test_class.client
        
        # Clean residual existing snapshots
        backups_engine.clean_backups()

        # Pull shared backups
        backups_engine.pull_shared_backups()

        # Get post-pull snapshot count
        pulled_snapshots = client.describe_db_snapshots(
            DBInstanceIdentifier=RDS_INSTANCE_RESOURCE_NAME,
            SnapshotType='Manual'
        )

        # Verify that only one snapshot was pulled
        self.assertEqual(len(pulled_snapshots["DBSnapshots"]), 1)
        
    @pytest.mark.cleanup
    def test_cleanup(self):
        # Instantiate test resource class
        rds_instance_test_class = RDSInstanceTestClass()
        backups_engine = rds_instance_test_class.backups_engine
        # Clean backups
        backups_engine.clean_backups()




        


    