#!/bin/bash

set -ex

DIR=$(readlink -f "$(dirname "$0")")
cd $DIR

serverless package
res/update_streetwarp.sh
zip -9 --symlinks -r .serverless/streetwarp-lambda.zip res