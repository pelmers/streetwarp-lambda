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
import subprocess
import aiohttp
import shutil
import os
import uuid


r = lambda p: os.path.join(dirname, *p.split("/"))
dirname = os.path.abspath(os.path.dirname(__file__))
bin_path = r("res/bin")
sw_path = r("res/bin/streetwarp")
blob_connection_envs = {
    "na": "AZURE_STORAGE_CONNECTION_STRING_NA",
    "eu": "AZURE_STORAGE_CONNECTION_STRING_EU",
    "as": "AZURE_STORAGE_CONNECTION_STRING_AS",
}
blob_service_client = None
ld_path = os.path.join(sw_path, "path_optimizer", "dist", "lib64")
if "LD_LIBRARY_PATH" in os.environ:
    os.environ["LD_LIBRARY_PATH"] += os.path.pathsep + ld_path
else:
    os.environ["LD_LIBRARY_PATH"] = ld_path


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
        command, *args, stdout=PIPE, stderr=PIPE, limit=1000 * 1000 * 10  # 10 MB
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


@timer("prepare output with EFS")
def prepare_output_efs(key):
    efs_id = str(uuid.uuid4())[:13]
    out_dir = os.path.join("/mnt/efs/", efs_id)
    os.mkdir(out_dir)
    out_name = os.path.join(out_dir, f"{key}.mp4")
    return (out_dir, out_name)


@timer("connect to progress endpoint")
async def connect_progress(endpoint):
    socket = None
    try:
        socket = await ws.connect(endpoint)
        print(f"Connected to server {endpoint}")
    except Exception as e:
        print(f"Could not connect websocket: {str(e)}")
    return socket


@timer("joining videos")
async def join_videos(event):
    callback_endpoint = event["callbackEndpoint"]
    video_urls = event["videoUrls"]
    key = event["key"]
    out_dir, out_name = prepare_output_efs(key)
    socket_task = asyncio.create_task(connect_progress(callback_endpoint))

    async def progress(msg):
        socket = await socket_task
        if socket is not None:
            wrapper = {"payload": msg, "key": key}
            await socket.send(json.dumps(wrapper))

    def short_progress(msg):
        asyncio.get_event_loop().create_task(
            progress({"type": "PROGRESS_STAGE", "stage": msg})
        )

    @timer("downloading videos")
    async def download_videos():
        @timer("fetching file")
        async def fetch(session, url):
            async with session.get(url, timeout=60) as response:
                res = await response.read()
                name = os.path.join(out_dir, url.rsplit("/", 1)[-1])
                with open(name, "wb") as f:
                    f.write(res)
                print(f"{url} downloaded to {name}")
                return name

        async with aiohttp.ClientSession() as session:
            return await asyncio.gather(
                *[
                    fetch(
                        session,
                        url,
                    )
                    for url in video_urls
                ]
            )

    @timer("concat videos with ffmpeg")
    def concat_videos(video_files):
        # https://stackoverflow.com/questions/7333232/how-to-concatenate-two-mp4-files-using-ffmpeg
        flist = os.path.join(out_dir, "file_list.txt")
        last_vid = video_files[0]
        index = 1
        for v in video_files[1:]:
            with open(flist, "w") as f:
                f.writelines([f"file '{v}'\n" for v in [last_vid, v]])
            new_vid = os.path.join(out_dir, f"fold_{index}.mp4")
            args = [
                r("res/bin/ffmpeg"),
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                flist,
                "-c",
                "copy",
                new_vid,
            ]
            print(f"args: {' '.join(args)}")
            subprocess.check_call(args)
            os.remove(last_vid)
            os.remove(v)
            last_vid = new_vid
            index += 1
        os.rename(last_vid, out_name)

    @timer("upload result")
    async def upload_vid():
        if blob_service_client is not None:
            name = f"{key}.mp4"
            client = blob_service_client.get_container_client("output").get_blob_client(
                f"{key}.mp4"
            )
            with open(out_name, "rb") as mp4:
                client.upload_blob(mp4)
            return client.url

    try:
        short_progress("Downloading video segments")
        video_files = await download_videos()
        short_progress("Joining video segments")
        concat_videos(video_files)
        result = {}
        if blob_service_client is not None:
            url = await upload_vid()
            print(f"Upload location: {url}")
            result["videoResult"] = {"url": url}
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
    finally:
        socket = await socket_task
        if socket is not None:
            await socket.close()
        shutil.rmtree(out_dir)


async def main_async(event):
    region = event["uploadRegion"] if "uploadRegion" in event else "na"
    global blob_service_client
    if region in blob_connection_envs:
        conn_str = os.environ[blob_connection_envs[region]]
        blob_service_client = BlobServiceClient.from_connection_string(conn_str)

    if "joinVideos" in event and event["joinVideos"]:
        return await join_videos(event)

    key = event["key"]
    index = None if "index" not in event else event["index"]
    args = event["args"]
    use_optimizer = event["useOptimizer"]
    extension = event["extension"]
    contents = event["contents"]
    callback_endpoint = event["callbackEndpoint"]

    in_file = prepare_input(key, contents, extension)
    out_dir, out_name = prepare_output(key)
    args += ["--output-dir", out_dir, "--output", out_name, in_file]
    if use_optimizer:
        args += ["--optimizer", os.path.join(sw_path, "path_optimizer", "main.py")]
    socket = await connect_progress(callback_endpoint)

    async def progress(msg):
        if socket is not None:
            wrapper = {"payload": msg, "key": key, "index": index}
            await socket.send(json.dumps(wrapper))

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
                    asyncio.get_event_loop().create_task(progress(msg))
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
            name = f"{key}.mp4" if index is None else f"seg_{key}_{index}.mp4"
            client = blob_service_client.get_container_client("output").get_blob_client(
                name
            )
            upload_vid(client)
            print(f"Upload location: {client.url}")
            result["videoResult"] = {"url": client.url}
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
    finally:
        if socket is not None:
            await socket.close()
        shutil.rmtree(out_dir)


@timer("main function")
def main(event, _context):
    return asyncio.get_event_loop().run_until_complete(main_async(event))
