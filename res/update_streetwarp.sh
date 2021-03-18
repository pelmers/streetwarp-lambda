#!/bin/bash

set -e

DIR=$(dirname $0)
cd $DIR/bin

rm -rf streetwarp
mkdir streetwarp
cd ../../../streetwarp
docker run --rm -it -v "$(pwd)":/home/rust/src ekidd/rust-musl-builder cargo build --release
bash ./path_optimizer/package.sh

cp target/x86_64-unknown-linux-musl/release/streetwarp $DIR/bin/streetwarp
cp -r path_optimizer $DIR/bin/streetwarp
