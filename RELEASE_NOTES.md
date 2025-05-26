# Shelvery Release Notes

## Version 0.9.11

### 🔨 Improvements

* Enhanced tag retrieval safety for multiple AWS services:
  * RDS Instances
  * RDS Clusters
  * DocumentDB Clusters

### 🐛 Bug Fixes

* Fixed potential crashes when handling resources without tags by implementing safe tag retrieval
* Added defensive programming to handle cases where TagList might be empty or missing
* Improved error handling for tag-related operations across multiple services

### 🔧 Technical Changes

* Modified tag retrieval logic in multiple files:
  * `rds_backup.py`: Implemented safe tag retrieval using `.get('TagList', [])`
  * `rds_cluster_backup.py`: Added defensive tag handling
  * `documentdb_backup.py`: Enhanced tag retrieval safety
* Updated version from 0.9.10 to 0.9.11 across configuration files

### 📝 Notes

* This release focuses on improving the robustness of tag handling operations
* No changes to core backup functionality or backup creation process
* Backwards compatible with existing configurations