import sys
import unittest
import os
import pytest

pwd = os.path.dirname(os.path.abspath(__file__))

sys.path.append(f"{pwd}/..")
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery_tests.docdb_integration_test import DocDBTestClass
from shelvery_tests.test_functions import setup_destination

class ShelveryDocDBPullTestCase(unittest.TestCase):
    
    @pytest.mark.destination
    def test_PullDocDbBackup(self):
        
        print(f"Doc DB - Running pull shared backups test")
        setup_destination()
    
        # Instantiate test resource class
        docdb_test_class = DocDBTestClass()
        backups_engine = docdb_test_class.backups_engine
        client = docdb_test_class.client

        # Pull shared backups
        backups_engine.pull_shared_backups()

        # Get post-pull snapshot count
        pulled_snapshots = client.describe_db_cluster_snapshots(
            DBClusterIdentifier='shelvery-test-docdb',
            SnapshotType='Manual'
        )

        # Verify that only one snapshot was pulled
        self.assertEqual(len(pulled_snapshots['DBClusterSnapshots']), 1)

    @pytest.mark.cleanup
    def test_cleanup(self):
        # Instantiate test resource class
        test_resource_class = DocDBTestClass()
        backups_engine = test_resource_class.backups_engine

        backups_engine.clean_backups()

    