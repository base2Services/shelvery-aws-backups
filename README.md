# Shelvery

Shelvery creates backups in Amazon Web Services(AWS). It is primarly designed to be run as an AWS Lambda
Function, but can be installed as a regular python package, and run as a CLI tool.

Shelvery currently supports the following resource types

- EBS volumes
- EC2 Instances (backups as AMIs)
- RDS Instances
- RDS Clusters
- Redshift Clusters (limited support)

## The Shelvery strategy

Shelvery makes a distinction in the space of aws backup tools by *unifying backup and retention periods logic*
within single class called `ShelveryEngine` - `shelvery/engine.py`. It differentiates itself from tooling that only allows
linear retention periods (e.g. 28days). Shelvery enables father-son-grandson backup strategies, effectively
enabling administrators to "keep the last 7 daily backups, but also the last 12 monthly backups, created on 1st of each month"
Supported levels of retention are - daily, weekly (created on Sundays), monthly (created 1st of each month), and yearly
backups (created on 1st of January). A general idea is that the more you walk back in past on the timeline,
less dense backups are.

Shelvery also supports backups across multiple accounts without the need to have implemented Organizations.

Shelvery *does not* cater for backup restore process.

## Features

- Create and clean EBS Volume backups
- Create and clean RDS Instance backups
- Create and clean RDS Cluster backups
- Create and clean EC2 Instance backups in form of Amazon Machine Images.
- Create and clean Redshift manual backups
- Get notified about all operations performed by Shelvery via SNS Topic
- Share backups with other accounts automatically
- Copying backups shared by other AWS accounts automatically
- Copy backups to disaster recovery AWS regions
- Multiple levels of configuration, with priorities: Resource tags, Lambda payload, Environment Variables, Config defaults

## Installation and usage

### As Cli

Shelvery is published to PyPI as python package, and can be obtained from there. Additionally, you can
clone this repository and deploy it as lambda.

Below is an example for installing shelvery within docker `python:3` image, and doing some configuration steps.

```shell
# run within docker container (preffered, as it has clean python3 install)
docker run --rm -it -v $HOME/.aws:/root/.aws -w /shelvery -e 'AWS_DEFAULT_REGION=us-east-1' python:3 bash

# install shelvery package
pip install shelvery

# configure (optional)
export shelvery_dr_regions=us-east-2
export shelvery_keep_daily_backups=7

# create rds cluster backups
shelvery ec2ami create_backups

# cleanup rds cluster backups
shelvery ec2ami clean_backups

# create ebs backups
shelvery ebs create_backups

# create rds backups
shelvery rds create_backups

# cleanup ebs backups
shelvery ebs clean_backups

# cleanup rds backups
shelvery rds clean_backups

# create rds cluster backups
shelvery rds_cluster create_backups

# cleanup rds cluster backups
shelvery rds_cluster clean_backups

# create redshift backups
shelvery redshift create_backups

# cleanup redshift cluster backups
shelvery redshift clean_backups
```

### Deploy as lambda

Shelvery can be deployed as a lambda fucntion to AWS using [serverless](www.serverless.com) framework. Serverless takes
care of creating the necessary IAM roles. It also adds daily scheduled backups of all supported resources at 1AM UTC,
and will run backup cleanup at 2AM UTC. Schedules are created as CloudWatch event rules.
Look at `serverless.yml` file for more details. For this method of installation (that is deployment)
there is no python package, and you'll need to clone the project. Below is an example of doing this process within a
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

## Delayed operations

Sharing a backup with another AWS account, or copying backup to another region is considered
delayed operation that should be executed in separate thread, or in case of running on AWS lambda context,
in another Lambda function invocation. This makes shelvery execution non-linear, in order to allow fanning out
share/copy operations on larger number of backups.

If you want ot enforce linear execution (only possible when running as CLI), set environment variable `SHELVERY_MONO_THREAD=1`.
This will ensure all shares / copies are done in single thread, and can prolong backup creation execution, as backup must be
in *available* state prior it can be shared or copied.

## AWS Credentials configuration

Shelvery uses boto3 as client library to communicate with Amazon Web Services. Use any environment variables that
boto3 supports to configure credentials. In Amazon Lambda environment, shelvery will pick up IAM credentials from
IAM role that Lambda is running under.

## Runtime environment

Shelvery requires Python3.6 to run. You can run it either from any server or local machine capable of interpreting
Python3.6 code, or as Amazon Lambda functions. All Shelvery code is written in such way that it supports
both CLI and Lambda execution.

## Backup lifecycle and retention periods

Any backups created via shelvery will get tagged with metadata, including backup name, creation time, and backup retention type (daily, weekly, monthly or yearly). Retention is following Grandfather-father-son [backup scheme](https://en.wikipedia.org/wiki/Backup_rotation_scheme).
Stale backups are cleaned using cleanup commands, according to retention policy.
Default retention policy is as follows

- Keep daily backups for 14 days
- Keep weekly backups for 8 weeks
- Keep monthly backups for 12 months
- Keep yearly backups for 10 years

Only one type of backup is created per shelvery run, and determined by current date. Rules are following

1. If running shelvery on 1st January, yearly backups will be created
2. If running shelvery on 1st of the month, monthly backup will be created
3. If running shelvery on Sunday, weekly backup will be created
4. Any other day, daily backup is being created

All retention policies can be tweaked using runtime configuration, explained in the **Runtime Configuration** section
Retention period is calculated at cleanup time, meaning lifetime of the backup created is not fixed, e.g. determined
at backup creation, but rather dynamic. This allows greater flexibility for the end user - e.g. extending daily backup
policy from last 7 to last 14 days will preserve all backups created in past 7 days, for another 7 days.

## What resources are being backed up

For following resource types:

- EC2 Volumes
- EC2 Instances
- RDS Instances
- RDS Clusters
- Redshift Clusters

Simply  add `shelvery:create_backup` tag with any of the following values

- `True`
- `true`
- `1`

to resource that should be backed up.

Resources that are not marked to be manage by shelvery are skipped.
Optionally you can export `shelvery_select_entity` environment variable to select single resource, though
tagging condition still applies.

## Notifications

All shelvery operations are being pushed to SNS topics, if configured (see `shelvery_sns_topic` and `shelvery_error_sns_topic` key in
RuntimeConfiguration section below), whether success or failure. From SNS topic you send emails,
subscribe custom Lambda functions, send payload to HTTP(S) endpoints etc. This allows monitoring systems
to hook into shelvery, and possibly alert on any errors occurred.

## Supported services

### EC2

EBS Backups in form of EBS Snapshots is supported. EC2 Instance backups in form of Amazon Machine Images (AMIs) is supported as well.

### RDS

RDS Backups are supported in form of RDS Snapshots. There is no support for sql dumps at this point. By default, RDS
snapshots are created as copy of the last automated snapshot. Set configuration key `shelvery_rds_backup_mode` to `RDS_CREATE_SNAPSHOT`
if you wish to directly create snapshot. Note that this may fail if RDS instance is not in `available` state

### RDS Clusters

RDS Cluster backups behave same as RDS instance backups, just on RDS Clusters (Aurora). Value of `shelvery_rds_backup_mode` has the same effect as for RDS instance backups.

### Redshift clusters

Redshift cluster snapshots are supported to an extent. Creating and cleaning backups is fully supported,
whereas copying snapshot to DR region (or pulling shared snapshot from DR account) is not
supported natively through API, but can be achieved using data transfer through S3 buckets,
`UNLOAD/COPY` statements, and `EnableSnapshotCopy` API call. This operations however are currenlty outside
of Shelvery scope

## Runtime Configuration

There are multiple configuration options for the shelvery backup engine, configurable on multiple levels.
Levels with higher priority number take precedence over the ones with lower priority number. Lowest priority
are defaults that are set in code. Look at `shelvery/runtime_config.py` source code file for more information.

### Keys

Available configuration keys are listed below:

- `shelvery_keep_daily_backups` - Number of days to retain daily backups
- `shelvery_keep_weekly_backups` - Number of weeks to retain weekly backups
- `shelvery_keep_monthly_backups` - Number of months to keep monthly backups
- `shelvery_keep_yearly_backups` - Number of years to keep yearly backups

- `shelvery_custom_retention_types` - custom retention periods in name:seconds (quarterHourly:86400) format, comma separated, empty (disabled) by default
- `shelvery_current_retention_type` - custom retention period applied to current create backup process

- `shelvery_dr_regions` - List of disaster recovery regions, comma separated
- `shelvery_wait_snapshot_timeout` - Timeout in seconds to wait for snapshot to become available before copying it
to another region or sharing with other account. Defaults to 1200 (20 minutes)
- `shelvery_share_aws_account_ids` -  AWS Account Ids to share backups with. Applies to both original and regional backups                                                                   
- `shelvery_source_aws_account_ids` - List of AWS Account Ids, comma seperated, that are exposing/sharing their shelvery
    backups with account where shelvery is running. This can be used for having DR aws account that aggregates backups
    from other accounts.
- `shelvery_bucket_name_template` - Template used to create bucket name. Available keys: `{account_id}`, `{region}`. Defaults to `shelvery.data.{account_id}-{region}.base2tools`
- `shelvery_rds_backup_mode` - can be either `RDS_COPY_AUTOMATED_SNAPSHOT` or `RDS_CREATE_SNAPSHOT`. Values are self-explanatory
- `shelvery_redshift_backup_mode` - can be either `REDSHIFT_COPY_AUTOMATED_SNAPSHOT` or `REDSHIFT_CREATE_SNAPSHOT`. Values are self-explanatory
- `shelvery_lambda_max_wait_iterations` - maximum number of chained calls to wait for backup availability
when running Lambda environment. `shelvery_wait_snapshot_timeout` will be used only in CLI mode, while this key is used only
on Lambda

- `shelvery_select_entity` - select only single resource to be backed up, rather than all tagged with shelvery tags.
This resource still needs to have shelvery tag on it to be backed up.

- `shelvery_sns_topic` - SNS Topic to publish event messages, including error messages for failed
backups
- `shelvery_error_sns_topic` - SNS Topic for receiving just errors. If not set all messages will be sent through `shelvery_sns_topic` topic
- `shelvery_source_aws_account_ids` - Comma-separated list of AWS account ids to pull backups from

- `shelvery_copy_resource_tags` - Copy tags from original resource [boolean]
- `shelvery_exluded_resource_tag_keys` - Comma separated list of tag keys to exclude from copying from original

- `shelvery_sqs_queue_url` - SQS queue url
- `shelvery_sqs_queue_wait_period` - sqs waiting period in seconds. [int] 0-900

- `shelvery_ignore_invalid_resource_state` - ignore exceptions due to the resource being in a unavailable state, such as shutdown, rebooting. Default value is `False`. [boolean]

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

Any keys passed to the lambda function event payload (if shelvery is running in Lambda environment), under `config` key will hold priority over environment variables. E.g. following payload will clean ebs backups, with rule to delete dailies older
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

### Custom retention periods

Custom retention periods can be set using `shelvery_custom_retention_types` formatted as `[name:retention period]` where retention period defined in seconds.
Multiple periods can be set using a comma separated list.

```text
shelvery_custom_retention_types=quarterHourly:86400,hourly:172800
```

When triggering shelvery on the desired schedule, specify the retention type using `shelvery_current_retention_type` tag with the desired retention type

```text
shelvery_current_retention_type=quarterHourly
```

## Multi account setup

Shelvery allows setting up disaster recovery AWS account with
all of the backups from organisations AWS accounts copied to
'disaster recovery' account.

1) Sharing backups with other accounts

```bash
# this runs in every
# running in account 222222222222,333333333333
$ export AWS_DEFAULT_PROFILE=source_account
$ export shelvery_share_aws_account_ids=111111111111
$ shelvery ebs create_backups
```

2) Copying shared backups from other acccount into current account

```bash
# this is running in destination account, let's say 111111111111
$ export AWS_DEFAULT_PROFILE=dst_account
$ export shelvery_source_aws_account_ids=222222222222,333333333333
# this command will pull backups from both accounts
$ shelvery ebs pull_shared_backups
```

## Waiting on backups to complete

By default shelvery will wait by sleeping and then querying the aws api for a complete status.
If this is not your preferred method you can offload the sleep to SQS to save costs on lambda compute.

You can set the sqs url and the wait period (seconds) before lambda is invoked to check on the status of the backup.
If the backup is not complete it will be passed back to sqs to wait for the same period.

```text
shelvery_sqs_queue_url=https://sqs.us-east-1.amazonaws.com/111111111111/shelvery
shelvery_sqs_queue_wait_period=300
```

## Deploying with SAM template

1. Setup you aws credentials and set the region

    ```bash
    export AWS_PROFILE=profile
    export AWS_DEFAULT_REGION=ap-southeast-2
    ```

2. Run the `deploy-sam-template.sh` script with the options to deploy the template in the target account.

    - `-b` [required] source bucket to deploy the sam package to
    - `-v` [optional] shelvery version to deploy, defaults to `0.8.5`
