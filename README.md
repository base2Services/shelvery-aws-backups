# Shelvery

Shelvery is tool for creating backups in Amazon cloud (AWS). It currently supports RDS and EBS backups,
and AMI support is scheduled to be released soon.

## Installation

```shell
pip install shelvery

# create ebs backups
shelvery ebs create_backups

# create rds backups
shelvery rds create_backups

# cleanup ebs backups
shelvery ebs clean_backups

# cleanup rds backups
shelvery rds clean_backups

```

## AWS Credentials configuration

Shelvery uses boto3 as client library to communicate with Amazon Web Services. Use any environment variables that
boto3 supports to configure credentials. In Amazon Lambda environment, shelvery will pick up IAM credentials from 
IAM role that Lambda is running under. 

## Runtime environment

Shelvery requires Python3.6 to run. You can run it either from any server or local machine capable of interpreting 
Python3.6 code, or as Amazon Lambda functions. All Shelvery code is written in such way that it supports
both CLI and Lambda execution. 

## Backup lifecycle and retention periods

Any backups created via shelvery will get tagged with metadata, including backup name, creation time, and backup retention type
(daily, weekly, monthly or yearly). Retention is following Grandfather-father-son [backup scheme](https://en.wikipedia.org/wiki/Backup_rotation_scheme).
Stale backups are cleaned using cleanup commands, according to retention policy.
Default retention policy is as follows

- Keep daily backups for 14 days
- Keep weekly backups for 8 weeks
- Keep monthly backups for 12 months
- Keep yearly backups for 10 years

All retention policy can be tweaked using runtime configuration, explained in **Runtime Configuration** section

## Tagging your resources

Any resources tagged with `shelvery:create_backup` will be included for backups. This applies to EBS volumes,
EC2 instances and RDS instances. 

## Supported services

### EC2 

EBS Backups and Amazon Machine Images are supported (AMIs comming soon)

### RDS

RDS Backups are supported in from of RDS Snapshots. There is no sql dumps created. 

## Lambda deployments

You can deploy whole Shelvery tool to Lambda, with schedule to run once a day at 1am UTC by using serverless framework.
Schedule will

- Create backups for all supported resources
- Clean up backups for all supported resources

TBD deployment via serverless

## Runtime Configuration

There are multiple configuration options for shelvery backup engine, configurable either through lambda function payload
or through environment variables

### Lambda event payload

TBD
### Environment variables

TBD
