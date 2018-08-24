import json
import boto3
from shelvery import S3_DATA_PREFIX


class AwsHelper:
    

    @staticmethod
    def get_shelvery_bucket_policy(owner_id, share_account_ids, bucket_name):
        """
        Returns bucket policy allowing all destination accounts access to shared
        paths
        :param share_account_ids:
        :param bucket_name:
        :return:
        """
        policy_stmt = [{
            'Effect': 'Allow',
            'Principal':{'AWS':f"arn:aws:iam::{owner_id}:root"} ,
            'Action': ['s3:*'],
            'Resource': [
                f"arn:aws:s3:::{bucket_name}",
                f"arn:aws:s3:::{bucket_name}/*",
            ]
        }]
        if share_account_ids is not None:
            for shared_account_id in share_account_ids:
                policy_stmt.append({
                    'Effect': 'Allow',
                    'Principal':{'AWS':f"arn:aws:iam::{shared_account_id}:root"} ,
                    'Action': ['s3:Get*', 's3:List*'],
                    'Resource': [
                        f"arn:aws:s3:::{bucket_name}",
                    ]
                })
                policy_stmt.append({
                    'Effect': 'Allow',
                    'Principal':{'AWS':f"arn:aws:iam::{shared_account_id}:root"} ,
                    'Action': ['s3:*'],
                    'Resource': [
                        f"arn:aws:s3:::{bucket_name}/{S3_DATA_PREFIX}/shared/{shared_account_id}*",
                    ]
                })
        return json.dumps({'Version': '2012-10-17', 'Id': 'shelvery-generated', 'Statement': policy_stmt})

    @staticmethod
    def local_account_id():
        return boto3.client('sts').get_caller_identity()['Account']

    @staticmethod
    def local_region():
        return boto3.session.Session().region_name