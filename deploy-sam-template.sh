#!/bin/bash
set -e

SHELVERY_VERSION=0.8.4

while getopts ":b:v:a:" opt; do
  case $opt in
    b)
      BUCKET=$OPTARG
      ;;
    v)
      SHELVERY_VERSION=$OPTARG
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

rm -rf lib/*

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
docker run --rm -v $DIR:/dst -w /dst -u 1000 python:3 pip install shelvery==$SHELVERY_VERSION -t lib

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
  --output-template-file packaged-template.yaml

echo "updating/creating cloudformation stack shelvery"
aws cloudformation deploy \
  --force-upload \
  --no-fail-on-empty-changeset \
  --template-file ./packaged-template.yaml \
  --stack-name shelvery \
  --capabilities CAPABILITY_IAM
