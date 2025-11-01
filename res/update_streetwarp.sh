#!/bin/bash

set -ex

DIR=$(readlink -f "$(dirname "$0")")
cd $DIR/bin

rm -rf streetwarp
mkdir streetwarp
cd ../../../streetwarp-cli
docker run --rm -it -v "$(pwd)":/home/rust/src ekidd/rust-musl-builder:1.50.0 cargo build --release
bash ./path_optimizer/package.sh

cp target/x86_64-unknown-linux-musl/release/streetwarp $DIR/bin/streetwarp
cp -r path_optimizer $DIR/bin/streetwarp
