#!/bin/bash

set -e

DIR=$(readlink -f "$(dirname "$0")")
cd $DIR

./package_lambda.sh
aws s3 cp .serverless/streetwarp-lambda.zip s3://streetwarp/bundle.zip
aws lambda update-function-code --function-name streetwarp --s3-bucket streetwarp --s3-key bundle.zip --publish