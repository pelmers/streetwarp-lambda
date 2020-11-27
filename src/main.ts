import { BlobServiceClient } from '@azure/storage-blob';
import child_process from 'child_process';
import readline from 'readline';
import util from 'util';
import fs from 'fs';
import os from 'os';
import path from 'path';
import mkdirp from 'mkdirp';
import ws, { OPEN } from 'ws';
import {
    FetchMetadataResult,
    MESSAGE_TYPES,
    ProgressMessage,
    ProgressStageMessage,
} from './messages';
import { credential } from './secret';
import { APIGatewayProxyHandler, APIGatewayProxyResult } from 'aws-lambda';

type RequestParams = {
    key: string;
    args: string[];
    contents: string;
    extension: string;
    callbackEndpoint: string;
};

const r = (p: string) => path.resolve(__dirname, p);
const tempDir = os.tmpdir();
const tmp = (p: string) => path.resolve(os.tmpdir(), p);

const blobServiceClient = new BlobServiceClient(
    `https://${credential.accountName}.blob.core.windows.net`,
    credential
);

export const handler: APIGatewayProxyHandler = async (
    event,
    context
): Promise<APIGatewayProxyResult> => {
    async function run(
        cmd: string,
        args: string[],
        cwd: string = '.'
    ): Promise<number> {
        console.info(`Running: ${cmd} ${args.join(' ')}`);
        const cp = child_process.spawn(cmd, args, { cwd, stdio: 'pipe' });
        cp.stderr.on('data', (data) => console.error(data.toString().trim()));
        cp.stdout.on('data', (data) => console.info(data.toString().trim()));
        return new Promise<number>((resolve, reject) => {
            cp.on('error', reject);
            cp.on('exit', (code) => resolve(code));
        });
    }

    async function extractResources(): Promise<void> {
        const binPath = r('res/bin');
        await run('ls', ['-laht', binPath]);
        process.env['PATH'] = `${binPath}:${process.env['PATH']}`;
    }

    async function prepareInput(
        key: string,
        contents: string,
        extension: string
    ): Promise<string> {
        const dest = tmp('data/input');
        await mkdirp(dest);
        const input = path.resolve(dest, `${key}.${extension}`);
        await util.promisify(fs.writeFile)(input, contents);
        return input;
    }

    async function prepareOutput(
        key: string
    ): Promise<{ outputDir: string; outputName: string }> {
        const outputDir = tmp(`data/output/${key}`);
        await mkdirp(outputDir);
        const outputName = path.join(outputDir, `${key}.mp4`);
        return { outputDir, outputName };
    }

    async function streetwarp(args: string[]): Promise<FetchMetadataResult> {
        let result: FetchMetadataResult;
        const proc = child_process.spawn('streetwarp', args, {
            stdio: 'pipe',
            env: { RUST_BACKTRACE: '1', ...process.env },
        });
        console.log(`spawned streetwarp: ${ args.join(' ') }`);
        const stderrMessages: string[] = [];
        proc.stderr.on('data', (data) => stderrMessages.push(data));
        const rl = readline.createInterface({ input: proc.stdout });
        rl.on('line', (line) => {
            console.info(`streetwarp: ${line.slice(0, 80).trim()}`);
            let msg;
            try {
                msg = JSON.parse(line);
                if (
                    msg.type === MESSAGE_TYPES.PROGRESS ||
                    msg.type === MESSAGE_TYPES.PROGRESS_STAGE
                ) {
                    reportProgress(msg);
                } else {
                    result = msg;
                }
            } catch (e) {
                console.error(`Could not parse streetwarp output ${line}`);
            }
        });
        const exitCode = await new Promise<number>((resolve) => {
            proc.on('exit', (code) => {
                if (code !== 0) {
                    console.error('streetwarp failed', args);
                    console.error(`stderr: ${stderrMessages.join('')}`);
                }
                resolve(code || 0);
            });
        });
        rl.close();
        if (exitCode !== 0) {
            throw new Error(`streetwarp failed with exit code ${exitCode}`);
        }
        return result;
    }

    async function time<T>(message: string, promise: Promise<T>): Promise<T> {
        const start = Date.now();
        try {
            const res = await promise;
            console.info(`${message}: ${(Date.now() - start).toFixed(2)}ms`);
            return res;
        } catch (err) {
            console.error(
                `${message} failed with ${err.toString()}: ${(
                    Date.now() - start
                ).toFixed(2)}ms`
            );
            throw err;
        }
    }

    async function reportProgress(message: ProgressMessage | ProgressStageMessage) {
        if (!socket || socket.readyState !== OPEN) {
            return;
        }
        socket.send(JSON.stringify({ key, payload: message }));
    }
    const {
        key,
        args,
        extension,
        contents,
        callbackEndpoint,
    } = (event as unknown) as RequestParams;
    console.info(
        `args: ${JSON.stringify({
            key,
            args,
            callbackEndpoint,
            contents: (contents || '').slice(0, 100),
            extension,
        })}`
    );
    let socket: ws | undefined;
    if (callbackEndpoint) {
        socket = new ws(callbackEndpoint);
        socket.on('connect', () =>
            console.info(`Connected to server ${callbackEndpoint}`)
        );
        socket.on('error', (e: unknown) =>
            console.info(`Socket error: ${JSON.stringify(e)}`)
        );
    }
    const [input, { outputDir, outputName }] = await Promise.all([
        time('writing gpx to a file', prepareInput(key, contents, extension)),
        time('prepare output folders', prepareOutput(key)),
        time('extracting resources', extractResources()),
    ]);

    args.push('--output-dir', outputDir, '--output', outputName, input);
    try {
        const metadataResult = await time('run streetwarp', streetwarp(args));
        const client = blobServiceClient
            .getContainerClient('output')
            .getBlockBlobClient(`${key}.mp4`);
        let videoResult = null;
        if (args.indexOf('--dry-run') === -1) {
            await time('upload video', client.uploadFile(outputName));
            console.info(`Upload location: ${client.url}`);
            videoResult = { url: client.url };
        }

        return {
            statusCode: 200,
            body: JSON.stringify({
                metadataResult,
                videoResult,
            }),
        };
    } catch (e) {
        return {
            statusCode: 500,
            body: JSON.stringify({ error: (e as Error).message }),
        };
    } finally {
        if (socket && socket.readyState === ws.OPEN) {
            socket.close();
        }
    }
};
