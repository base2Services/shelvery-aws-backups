#!/bin/bash
set -e

SHELVERY_VERSION=0.9.13

# set DOCKERUSERID to current user. could be changed with -u uid
DOCKERUSERID="-u $(id -u)"

if [[ $1 == "help" ]]; then
  echo """
  Usage: 
    ./deploy-sam-template.sh -b my-s3-bucket -r us-west-2     # deploy latest shelvery version in the us-west-2 region
    ./deploy-sam-template.sh -b my-s3-bucket -l true -p true  # package and deploy the current git branch
  
  Options:
    -b BUCKET                     # s3 bucket to deploy the sam package to
    [-v VERSION]                  # set the shelvery version to deploy, defaults to $SHELVERY_VERSION
    [-r REGION]                   # AWS region to deploy shelvery, if not set it will get from the aws config or environment
    [-p true] BOOLEAN             # Build and package shelvery from the current branch. Use with '-l true' to deploy the package.
    [-l true] BOOLEAN             # install shelvery from a local dist build in the ./dist/shelvery-\${SHELVERY_VERSION}.tar.gz
    [-o KEY1=VALUE1,KEY2=VALUE2]  # Override cloudformation template parameters with a comma separated string of key value pairs
                                  # e.g. -o ShelveryRdsBackupMode=RDS_CREATE_SNAPSHOT,ShelveryEncryptCopy=true
    [-u UID]                      # Set the docker user id, defaults to $DOCKERUSERID
  """
  exit -1
fi

while getopts ":b:r:u:l:p:v:o:" opt; do
  case $opt in
    b)
      BUCKET=$OPTARG
      ;;
    v)
      SHELVERY_VERSION=$OPTARG
      ;;
    r)
      REGION=$OPTARG
      ;;
    l)
      LOCAL_INSTALL=$OPTARG
      ;;
    p)
      PACKAGE=$OPTARG
      ;;
    o)
      PARAM_OVERRIDES=$OPTARG
      ;;
    u)
      DOCKERUSERID=" -u $OPTARG"
      ;;
    \?)
      echo "Invalid option: -$OPTARG" >&2
      exit 1
      ;;
    :)
      echo "Option -$OPTARG requires an argument." >&2
      exit 1
      ;;
  esac
done

if [ -z ${BUCKET+x} ]; then
  echo "Source bucket not set with -b"
  exit 1
fi

if [ ! -z ${REGION} ]; then
  REGION="--region $REGION"
fi

rm -rf lib/*
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

if [[ ${PACKAGE} == 'true' ]]; then
    docker run --rm -v $DIR:/build -w /build $DOCKERUSERID python:3 python setup.py sdist
fi

if [[ ${LOCAL_INSTALL} == 'true' ]]; then
  echo "Installing shelvery $SHELVERY_VERSION from local sdist"
  docker run --rm -v $DIR:/dst -w /dst $DOCKERUSERID python:3 pip install ./dist/shelvery-${SHELVERY_VERSION}.tar.gz -t lib
else
  echo "Installing shelvery $SHELVERY_VERSION from pypi"
  docker run --rm -v $DIR:/dst -w /dst $DOCKERUSERID python:3 pip install shelvery==$SHELVERY_VERSION -t lib
fi

echo "packaging lambdas"
cd lib
zip shelvery.zip -r ./*
cd ..

PARAM_OPTS=""

if [ ! -z ${PARAM_OVERRIDES} ]; then
  PARAMS=($(echo ${PARAM_OVERRIDES} | tr ',' "\n"))
  PARAM_OPTS="--parameter-overrides"
  for p in "${PARAMS[@]}"
  do
    KEY=$(echo $p | cut -d'=' -f1)
    VALUE=$(echo $p | cut -d'=' -f2)
    PARAM_OPTS="${PARAM_OPTS} ParameterKey=${KEY},ParameterValue=${VALUE}" 
  done
fi

echo "packaging cloudformation"
sam package --template-file template.yaml --s3-bucket $BUCKET --s3-prefix cloudformation/shelvery --output-template-file packaged-template.yaml $REGION


echo "updating/creating cloudformation stack shelvery"
sam deploy --template-file ./packaged-template.yaml --stack-name shelvery --capabilities CAPABILITY_IAM $PARAM_OPTS $REGION
