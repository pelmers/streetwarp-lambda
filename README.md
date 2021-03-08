# Streetwarp-Lambda

This repo contains an AWS Lambda program which executes
[streetwarp](https://github.com/pelmers/streetwarp-cli) and uploads its output
to an Azure storage blob. It's designed to be called by
[streetwarp-web](https://github.com/pelmers/streetwarp-web).

`res/bin` contains static builds of streetwarp and ffmpeg which can execute on
AWS Lambda's Ubuntu runtime.

### Usage

To upload output to Azure, the program needs storage write credentials. Create
a file `src/secret.ts` which exports an Azure storage credential object.

Example:

```
import { StorageSharedKeyCredential } from '@azure/storage-blob';

const account = 'account name';
const accountKey = 'account key';
export const credential = new StorageSharedKeyCredential(account, accountKey);
```

### Publishing

To publish changes to the Lambda program, use AWS CLI tooling. First create a
zip, then upload to Lambda.

```
yarn
yarn run deploy
```

### Testing

Use the AWS Lambda Management Console to test this program by sending events
with the following format:

```
{
  "key": "xyz1234",
  "callbackEndpoint": "https://streetwarp-web-location",
  "args": [
    "--progress",
    "--api-key",
    "GOOGLE_API_KEY",
    "--print-metadata",
    "--dry-run",
    "--frames-per-mile",
    "0.5",
    "--json"
  ],
  "extension": "gpx",
  "contents": "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<gpx xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns=\"http://www.topografix.com/GPX/1/1\" xmlns:gpxdata=\"http://www.cluetrust.com/XML/GPXDATA/1/0\" xsi:schemaLocation=\"http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd http://www.cluetrust.com/XML/GPXDATA/1/0 http://www.cluetrust.com/Schemas/gpxdata10.xsd\" version=\"1.1\" creator=\"http://ridewithgps.com/\"></gpx>\n"
}
```
