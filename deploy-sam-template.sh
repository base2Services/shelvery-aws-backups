#!/bin/bash
set -e

SHELVERY_VERSION=0.9.4

# set DOCKERUSERID to current user. could be changed with -u uid
DOCKERUSERID="-u $(id -u)"

while getopts ":b:v:a:r:u:l:p:" opt; do
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

echo "packaging cloudformation"
aws cloudformation package \
  --force-upload \
  --template-file template.yaml \
  --s3-bucket $BUCKET \
  --s3-prefix cloudformation/shelvery \
  --output-template-file packaged-template.yaml \
  $REGION

echo "updating/creating cloudformation stack shelvery"
aws cloudformation deploy \
  --force-upload \
  --no-fail-on-empty-changeset \
  --template-file ./packaged-template.yaml \
  --stack-name shelvery \
  --capabilities CAPABILITY_IAM \
  $REGION
