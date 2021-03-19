try:
    import unzip_requirements
except ImportError:
    pass
import asyncio
from asyncio.subprocess import PIPE
from asyncio import create_subprocess_exec
import json, os, sys, subprocess
from time import monotonic
from functools import wraps
from tempfile import mkdtemp
from azure.storage.blob import BlobServiceClient
from contextlib import contextmanager
import websockets as ws


r = lambda p: os.path.join(dirname, *p.split("/"))
dirname = os.path.abspath(os.path.dirname(__file__))
bin_path = r("res/bin")
sw_path = r("res/bin/streetwarp")
to_cdn = lambda url: url
blob_connection_env = "AZURE_STORAGE_CONNECTION_STRING"
blob_service_client = (
    BlobServiceClient.from_connection_string(os.getenv(blob_connection_env))
    if blob_connection_env in os.environ
    else None
)


# Define decorator that lets us @timer('msg') on functions
def timer(msg):
    @contextmanager
    def wrapper():
        start = monotonic()
        yield
        print(f"{msg}: {(monotonic()-start)*1000:.3f}ms")

    def with_func(func):
        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def t_async(*args, **kwargs):
                with wrapper():
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        print(f"{msg} failed with {str(e)}.", file=sys.stderr)
                        raise e

            return t_async
        else:

            @wraps(func)
            def t(*args, **kwargs):
                with wrapper():
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        print(f"{msg} failed with {str(e)}.", file=sys.stderr)
                        raise e

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
            callback(line.decode("utf-8").strip())
        else:
            break


async def run(command, args, out_callback, err_callback):
    process = await create_subprocess_exec(
        command, *args,
        env={},
        stdout=PIPE, stderr=PIPE, limit=1000 * 1000 * 10  # 10 MB
    )

    await asyncio.wait(
        [
            _read_stream(process.stdout, out_callback),
            _read_stream(process.stderr, err_callback),
        ]
    )

    return await process.wait()


@timer("prepare output")
def prepare_output(key):
    out_dir = mkdtemp()
    out_name = os.path.join(out_dir, f"{key}.mp4")
    return (out_dir, out_name)


async def main_async(event):
    key = event["key"]
    args = event["args"]
    use_optimizer = event["useOptimizer"]
    extension = event["extension"]
    contents = event["contents"]
    callback_endpoint = event["callbackEndpoint"]
    socket = None
    try:
        socket = await ws.connect(callback_endpoint)
        print(f"Connected to server {callback_endpoint}")
    except Exception as e:
        print(f"Could not connect websocket: {str(e)}")

    in_file = prepare_input(key, contents, extension)
    out_dir, out_name = prepare_output(key)
    args += ["--output-dir", out_dir, "--output", out_name, in_file]
    if use_optimizer:
        args += ["--optimizer", os.path.join(sw_path, "path_optimizer", "main.py")]

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
        result = []

        def on_out(line):
            try:
                msg = json.loads(line)
                if "type" in msg and msg["type"] in ("PROGRESS", "PROGRESS_STAGE"):
                    print(f"streetwarp progress: {line}")
                    asyncio.get_event_loop().create_task(progress(line))
                else:
                    result.append(msg)
            except Exception as e:
                print(f"Could not parse streetwarp output {line}", file=sys.stderr)
                print(f"Error: {str(e)}", file=sys.stderr)

        def on_err(line):
            print(f"streetwarp err: {line}")
            stderr.append(line)

        exit_code = await run("streetwarp", args, on_out, on_err)
        if exit_code != 0:
            stderr = "\n".join(stderr)
            print(f'streetwarp failed (args=[{" ".join(args)}])', file=sys.stderr)
            print(f"stderr: {stderr}", file=sys.stderr)
            raise RuntimeError(f"streetwarp failed with exit code {exit_code}")
        return result[-1]

    try:
        metadata = await streetwarp()
        result = {"metadataResult": metadata}
        if "--dry-run" not in args and blob_service_client is not None:
            client = blob_service_client.get_container_client("output").get_blob_client(
                f"{key}.mp4"
            )
            upload_vid(client)
            print(f"Upload location: {client.url}")
            result["videoResult"] = {"url": to_cdn(client.url)}
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
    finally:
        if socket is not None:
            await socket.close()


@timer("main function")
def main(event, _context):
    return asyncio.get_event_loop().run_until_complete(main_async(event))
