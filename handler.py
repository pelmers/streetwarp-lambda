try:
    import unzip_requirements
except ImportError:
    pass
import asyncio
from asyncio.subprocess import PIPE
from asyncio import create_subprocess_exec
import json, os, sys, subprocess
from time import time
from pprint import pprint
from functools import wraps
from tempfile import mkdtemp
from azure.storage.blob import BlobServiceClient
import websockets as ws


r = lambda p: os.path.join(dirname, *p.split("/"))
dirname = os.path.abspath(os.path.dirname(__file__))
bin_path = r("res/bin")
sw_path = r("res/bin/streetwarp")
to_cdn = lambda url: url
blob_service_client = BlobServiceClient.from_connection_string(
    os.getenv("AZURE_STORAGE_CONNECTION_STRING")
)


# Define decorator that lets us @timer('msg') on functions
def timer(msg):
    def with_func(func):
        @wraps(func)
        def t(*args, **kwargs):
            start = time()
            try:
                return func(*args, **kwargs)
            except Exception as e:
                print(f"{msg} failed with {str(e)}.", file=sys.stderr)
                raise e
            finally:
                print(f"{msg}: {(time()-start)*1000:.3f}ms")

        return t

    return with_func


@timer("prepare input")
def prepare_input(key, contents, extension):
    os.environ["PATH"] += os.pathsep + bin_path
    os.environ["PATH"] += os.pathsep + sw_path
    dest = mkdtemp()
    inp = os.path.join(dest, f"{key}.{extension}")
    with open(inp, "w") as f:
        f.write(contents)
    return inp


# https://stackoverflow.com/a/53323746
async def _read_stream(stream, callback):
    while True:
        line = await stream.readline()
        if line:
            callback(line)
        else:
            break


async def run(command, args, out_callback, err_callback):
    process = await create_subprocess_exec(command, *args, stdout=PIPE, stderr=PIPE)

    await asyncio.wait(
        [
            _read_stream(process.stdout, out_callback),
            _read_stream(process.stderr, err_callback),
        ]
    )

    await process.wait()


@timer("prepare output")
def prepare_output(key):
    out_dir = mkdtemp
    out_name = os.path.join(out_dir, f"{key}.mp4")
    return (out_dir, out_name)


async def main_async(event):
    key = event["key"]
    args = event["args"]
    extension = event["extension"]
    contents = event["contents"]
    callback_endpoint = event["callbackEndpoint"]
    pprint(event)

    socket = None
    try:
        socket = await ws.connect(callback_endpoint)
        print(f"Connected to server {callback_endpoint}")
    except Exception as e:
        print(f"Could not connect websocket: {str(e)}")

    in_file = prepare_input(key, contents, extension)
    out_dir, out_name = prepare_output(key)
    args += ["--output-dir", out_dir, "--output", out_name, in_file]

    async def progress(msg):
        if socket is not None:
            await socket.send(msg)

    @timer("upload video")
    def upload_vid(client):
        with open(out_name, "rb") as mp4:
            client.upload_blob(mp4)

    @timer("run streetwarp")
    async def streetwarp():
        stderr = []
        result = None

        def on_out(line):
            try:
                msg = json.loads(line)
                if msg["type"] in ("PROGRESS", "PROGRESS_STAGE"):
                    asyncio.get_event_loop().create_task(progress(line))
                else:
                    result = msg
            except Exception as e:
                print(f"Could not parse streetwarp output {line}", file=sys.stderr)

        exit_code = await run(
            "streetwarp", args, on_out, lambda err: stderr.append(err)
        )
        if exit_code != 0:
            stderr = "\n".join(stderr)
            print(f'streetwarp failed (args=[{" ".join(args)}])', file=sys.stderr)
            print(f"stderr: {stderr}", file=sys.stderr)
            raise RuntimeError(f"streetwarp failed with exit code {exit_code}")
        return result

    try:
        metadata = streetwarp(args)
        result = {"metadataResult": metadata}
        if "--dry-run" not in args:
            client = blob_service_client.get_container_client("output").get_blob_client(
                f"{key}.mp4"
            )
            upload_vid(client)
            print(f"Upload location: {client.url}")
            result["videoResult"] = {"url": to_cdn(client.url)}
        pprint(result)
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as e:
        return {"statusCode": 500, body: json.dumps({"error": str(e)})}
    finally:
        if socket is not None:
            socket.close()


@timer("main function")
def main(event):
    return asyncio.get_event_loop().run_until_complete(main_async(event))


# expected result from test event:
# {
#  "statusCode": 200,
#  "body": "{\"metadataResult\":{\"distance\":21561.385533487017,\"frames\":6,\"gpsPoints\":[{\"lat\":47.58910167467456,\"lng\":-122.2529698647992},{\"lat\":47.55999707850386,\"lng\":-122.2265548264297},{\"lat\":47.52927704962136,\"lng\":-122.2326196099177},{\"lat\":47.55173931336428,\"lng\":-122.2131310793535},{\"lat\":47.5779808,\"lng\":-122.2100971},{\"lat\":47.5893092,\"lng\":-122.2529977}],\"originalPoints\":[{\"lat\":47.58911,\"lng\":-122.25297},{\"lat\":47.58907,\"lng\":-122.25297},{\"lat\":47.58891,\"lng\":-122.25299},{\"lat\":47.58884,\"lng\":-122.25299},{\"lat\":47.58874,\"lng\":-
