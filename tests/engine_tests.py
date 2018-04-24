import unittest
import sys
import os


pwd = os.path.dirname(os.path.abspath(__file__))
sys.path.append(f"{pwd}/../shelvery")
sys.path.append(f"{pwd}/shelvery")
sys.path.append(f"{pwd}/lib")
sys.path.append(f"{pwd}/../lib")

from shelvery.ebs_backup import ShelveryEBSBackup
from shelvery.rds_backup import ShelveryRDSBackup
from shelvery.factory import ShelveryFactory
from shelvery.ec2ami_backup import ShelveryEC2AMIBackup
from shelvery.rds_cluster_backup import ShelveryRDSClusterBackup

print(f"Python lib path:\n{sys.path}")

class ShelveryFactoryTestCase(unittest.TestCase):
    """Shelvery Factory unit tests"""
    
    def setUp(self):
        print(f"Setting up unit tests")
    
    def tearDown(self):
        print(f"Tear down unit tests")
    
    def test_getEbsShelvery(self):
        instance = ShelveryFactory.get_shelvery_instance('ebs')
        self.assertTrue(isinstance(instance, ShelveryEBSBackup))

    def test_getRdsShelvery(self):
        instance = ShelveryFactory.get_shelvery_instance('rds')
        self.assertTrue(isinstance(instance, ShelveryRDSBackup))

    def test_getRdsClusterBackup(self):
        instance = ShelveryFactory.get_shelvery_instance('rds_cluster')
        self.assertTrue(isinstance(instance, ShelveryRDSClusterBackup))

    def test_getRdsEc2AmiBackup(self):
        instance = ShelveryFactory.get_shelvery_instance('ec2ami')
        self.assertTrue(isinstance(instance, ShelveryEC2AMIBackup))
        
if __name__ == '__main__':
    unittest.main()
