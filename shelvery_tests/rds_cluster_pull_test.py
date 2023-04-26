import sys
import unittest
import os
import pytest
from shelvery_tests.rds_cluster_integration_test import RDSClusterTestClass
from shelvery_tests.test_functions import setup_destination
from shelvery_tests.resources import RDS_CLUSTER_RESOURCE_NAME

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

class ShelveryRDSClusterPullTestCase(unittest.TestCase):
    
    @pytest.mark.destination
    def test_PullRdsClusterBackup(self):
        
        # Complete initial setup
        print(f"RDS Cluster - Running pull shared backups test")
        setup_destination(self)
    
        # Instantiate test resource class
        rds_cluster_test_class = RDSClusterTestClass()
        backups_engine = rds_cluster_test_class.backups_engine
        client = rds_cluster_test_class.client
        
        # Clean residual existing snapshots
        backups_engine.clean_backups()

        # Pull shared backups
        backups_engine.pull_shared_backups()

        # Get post-pull snapshot count
        pulled_snapshots = client.describe_db_cluster_snapshots(
            DBClusterIdentifier=RDS_CLUSTER_RESOURCE_NAME,
            SnapshotType='Manual'
        )

        # Verify that only one snapshot was pulled
        self.assertEqual(len(pulled_snapshots['DBClusterSnapshots']), 1)

    @pytest.mark.cleanup
    def test_cleanup(self):
        # Instantiate test resource class
        rds_cluster_test_class = RDSClusterTestClass()
        backups_engine = rds_cluster_test_class.backups_engine
        # Clean backups
        backups_engine.clean_backups()



        


    