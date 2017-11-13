# Shelvery

Shelvery is tool for creating backups in Amazon cloud (AWS). It currently supports RDS and EBS backups,
and AMI support is scheduled to be released soon. 

## Features 

- Create and clean EBS Volume backups
- Create and clean RDS Instance backups
- Share backups with other accounts automatically
- Copy backups to disaster recovery AWS regions
- Multiple levels of configuration, with priorities: Resource tags, Lambda payload, Environment Variables, Config defaults

## Installation and usage

### As Cli

Below is example for installing shelvery within docker `python:3` image, and doing some configuration steps.


```shell
# run within docker container (preffered, as it has clean python3 install)
docker run --rm -it -v $HOME/.aws:/root/.aws -w /shelvery -e 'AWS_DEFAULT_REGION=us-east-1' python:3 bash


# install shelvery package
pip install shelvery

# configure (optional)
export shelvery_dr_regions=us-east-2
export shelvery_keep_daily_backups=7

# create ebs backups
shelvery ebs create_backups

# create rds backups
shelvery rds create_backups

# cleanup ebs backups
shelvery ebs clean_backups

# cleanup rds backups
shelvery rds clean_backups

```

### Deploy as lambda

Shelvery can be deployed as lambda fucntion to AWS using [serverless](www.serverless.com) framework. Serverless takes
care of creation of necessary IAM roles. It also adds daily scheduled to backup all supported resources at 1AM UTC, 
and to run backup cleanup at 2AM UTC. Schedules are created as CloudWatch event rules.
Look at `serverless.yml` file for more details. For this method of installation (that is deployment)
there is no python package, and you'll need to clone the project. Below is example from doing this process within 
`node` docker container

```text
$ docker run --rm -it -v $HOME/.aws:/root/.aws -w /src node:latest bash

root@4b2d6804c8d3:/src#  git clone https://github.com/base2services/shelvery && cd shelvery
Cloning into 'shelvery'...
remote: Counting objects: 114, done.
remote: Compressing objects: 100% (28/28), done.
remote: Total 114 (delta 19), reused 24 (delta 12), pack-reused 73
Receiving objects: 100% (114/114), 38.88 KiB | 0 bytes/s, done.
Resolving deltas: 100% (53/53), done.
Checking connectivity... done.
root@4b2d6804c8d3:/src/shelvery# npm install -g serverless
/usr/local/bin/slss -> /usr/local/lib/node_modules/serverless/bin/serverless
/usr/local/bin/serverless -> /usr/local/lib/node_modules/serverless/bin/serverless
/usr/local/bin/sls -> /usr/local/lib/node_modules/serverless/bin/serverless

> spawn-sync@1.0.15 postinstall /usr/local/lib/node_modules/serverless/node_modules/spawn-sync
> node postinstall


> serverless@1.24.1 postinstall /usr/local/lib/node_modules/serverless
> node ./scripts/postinstall.js


┌───────────────────────────────────────────────────┐
│          serverless update check failed           │
│        Try running with sudo or get access        │
│       to the local update config store via        │
│ sudo chown -R $USER:$(id -gn $USER) /root/.config │
└───────────────────────────────────────────────────┘
+ serverless@1.24.1
added 296 packages in 13.228s


root@4b2d6804c8d3:/src/shelvery# sls deploy
Serverless: Packaging service...
Serverless: Excluding development dependencies...
Serverless: Uploading CloudFormation file to S3...
Serverless: Uploading artifacts...
Serverless: Uploading service .zip file to S3 (56.26 KB)...
Serverless: Validating template...
Serverless: Updating Stack...
Serverless: Checking Stack update progress...
.........
Serverless: Stack update finished...
Service Information
service: shelvery
stage: dev
region: us-east-1
stack: shelvery-dev
api keys:
  None
endpoints:
  None
functions:
  shelvery: shelvery-dev-shelvery
Serverless: Removing old service versions...

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

Only one type of backups is created per shelvery run, and determined by current date. Rules are following

1. If running shelvery on 1st January, yearly backups will be created
2. If running shelvery on 1st of the month, monthly backup will be created
3. If running shelvery on Sunday, weekly backup will be created
4. Any other day, daily backup is being created

All retention policy can be tweaked using runtime configuration, explained in **Runtime Configuration** section
Retention period is calculated at cleanup time, meaning lifetime of the backup created is not fixed, e.g. determined
at backup creation, but rather dynamic. This allows greater flexibility for the end user - e.g. extending daily backup 
policy from last 7 to last 14 days will preserve all backups created in past 7 days, for another 7 days. 

## Marking your resources to be backed up by tagging

Any resources tagged with `shelvery:create_backup` will be included for backups. This applies to EBS volumes,
EC2 instances and RDS instances. 

## Supported services

### EC2 

EBS Backups in form of EBS Snapshots is supported. Support for EC2 instances backup in form
of AMI is on the roadmap. 

### RDS

RDS Backups are supported in form of RDS Snapshots. There is no support for sql dumps at this point. By default, RDS
snapshots are created as copy of the last automated snapshot. Set configuration key `` to `RDS_CREATE_SNAPSHOT`
if you wish to directly create snapshot. Note that this may fail if RDS instance is not in `vaiable`


## Runtime Configuration

There are multiple configuration options for shelvery backup engine, configurable on multiple levels. 
Level with higher priority number take precedence over the ones with lower priority number. Lowest priority
are defaults that are set in code. Look at `shelvery/runtime_config.py` source code file for more information. 

### Keys

Available configuration keys are below

- `shelvery_keep_daily_backups` - Number of days to retain daily backups
- `shelvery_keep_weekly_backups` - Number of weeks to retain weekly backups
- `shelvery_keep_monthly_backups` - Number of months to keep monthly backups
- `shelvery_keep_yearly_backups` - Number of years to keep yearly backups
- `shelvery_dr_regions` - List of disaster recovery regions, comma separated
- `shelvery_wait_snapshot_timeout` - Timeout in seconds to wait for snapshot to become available before copying it 
to another region or sharing with other account. Defaults to 1200 (20 minutes)
- `shelvery_share_aws_account_ids` -  AWS Account Ids to share backups with. Applies to both original and regional backups                                                                   
- `shelvery_rds_backup_mode` - can be either `RDS_COPY_AUTOMATED_SNAPSHOT` or `RDS_CREATE_SNAPSHOT`. Values are self-explanatory
- `shelvery_lambda_max_wait_iterations` - maximum number of chained calls to wait for backup availability
when running Lambda environment. `shelvery_wait_snapshot_timeout` will be used only in CLI mode, while this key is used only
on Lambda


### Configuration Priority 0: Sensible defaults

```text
shelvery_keep_daily_backups=14
shelvery_keep_weekly_backups=8
shelvery_keep_monthly_backups=12
shelvery_keep_yearly_backups=10
shelvery_wait_snapshot_timeout=120
shelvery_lambda_max_wait_iterations=5
```


### Configuration Priority 1: Environment variables

```shell
$ export shelvery_rds_backup_mode=RDS_CREATE_SNAPSHOT
$ shelvery rds create_backups
```

### Configuration Priority 2: Lambda Function payload

Any keys passed to lambda function payload (if shelvery is running in Lambda environment), under `config` key will hold
priority over environment variables. E.g. following payload will clean ebs backups, with rule to delete dailies older
than 5 days

```json
{
  "backup_type": "ebs",
  "action": "clean_backups",
  "config": {
    "shelvery_keep_daily_backups": 5
  }
}
```

### Configuration Priority 3: Resource tags

Resource tags apply for retention period and DR regions. E.g. putting following tag on your EBS volume, 
will ensure it's daily backups are retained for 30 days, and copied to `us-west-1` and `us-west-2`.
`shelvery_share_aws_account_ids` is not available on a resource level (Pull Requests welcome)

`shelvery:config:shelvery_keep_daily_backups=30`
`shelvery:config:shelvery_dr_regions=us-west-1,us-west-2`

Generic format for shelvery config tag is `shevlery:config:$configkey=$configvalue`

