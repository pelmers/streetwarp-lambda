# Streetwarp-Lambda

This repo contains an AWS Lambda program which executes
[streetwarp](https://github.com/pelmers/streetwarp-cli) and uploads its output
to an Azure storage blob. It's designed to be called by
[streetwarp-web](https://github.com/pelmers/streetwarp-web). See it in action at [streetwarp.com](https://streetwarp.com/).

`res/bin` contains a static build of ffmpeg which can execute on
AWS Lambda's Amazon Linux runtime.

### Testing Locally
**Prereqs:**:
 - [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
 - `test/testoutput.json` created locally, following [event format](#event-format)
 - [Docker](https://www.docker.com/), for build and deployment

**Steps:**
1. `npm install -g serverless`
2. `npm install`
3. `poetry install`
4. `./package_lambda.sh`
5. `sam local invoke -e test/testoutput.json`

**Formatting:**
`black handler.py`

### Usage

To upload output to Azure, the program needs storage write credentials. It expects
to find this in the environment variable AZURE_STORAGE_CONNECTION_STRING.


### Details

This lambda handler function has two operating modes:
  1. creating a streetwarp video from input json or GPX data
  2. joining multiple videos into a single larger one

In its current operation on [streetwarp.com](https://streetwarp.com/), routes are
chunked down to 600 points and a batch of calls to mode 1 of this handler are
made. These videos are uploaded to Azure storage with the pattern
`[key]_[index].mp4`.

Once complete, a second call is made to join all these
videos together. The handler enters this mode by checking the `joinVideos` key
of the event data. In this case the video segments are downloaded to [Amazon EFS](https://aws.amazon.com/efs/), joined with `ffmpeg`, then uploaded to Azure and deleted from EFS. The programs assumes EFS is mounted at `/mnt/efs`.

### Publishing

To publish changes to the Lambda program, use AWS CLI tooling. First create a
zip, then upload to Lambda. The packaging script **expects
[streetwarp](https://github.com/pelmers/streetwarp-cli) checked out in a sibling directory**.

```
npm install
./package_lambda.sh
./deploy_lambda.sh
```

### Event format

Use the AWS Lambda Management Console to test this program by sending events
with the following format:

```
{
  "key": "xyz1234",
  "callbackEndpoint": "https://streetwarp-web-location",
  "useOptimizer": true,
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
