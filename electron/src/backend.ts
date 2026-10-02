import { type ChildProcess, spawn } from 'node:child_process';
import net from 'node:net';
import type { LogFile } from './logFile';

const HOST = '127.0.0.1';
/** Python, the core and the stored servers start before the server listens. */
const READY_TIMEOUT_MS = 60_000;
const READY_POLL_MS = 150;
/** The server stops its tasks and the core, then closes the database. */
const STOP_TIMEOUT_MS = 10_000;
const KILL_TIMEOUT_MS = 3_000;
/** A start can lose its port to another program between choosing it and listening. */
const START_ATTEMPTS = 3;

export class BackendError extends Error {}

export interface BackendOptions {
  /** The Python executable. */
  python: string;
  /** The folder with the server package; it finds the web client and the core from it. */
  directory: string;
  /** XPR_DATA_DIR of the server. */
  data: string;
  log: LogFile;
  /** The server exited by itself after it had started. */
  onExit: (code: number | null) => void;
}

/** A port free now; the OS does not hand it out again at once. */
export function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once('error', reject);
    server.listen(0, HOST, () => {
      const address = server.address();
      server.close(() => {
        if (address && typeof address === 'object') resolve(address.port);
        else reject(new BackendError('No free port for the interface'));
      });
    });
  });
}

/** Whether something accepts TCP connections on the port. */
function listening(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.connect({ host: HOST, port });
    socket.once('connect', () => {
      socket.destroy();
      resolve(true);
    });
    socket.once('error', () => resolve(false));
  });
}

function exited(child: ChildProcess): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

function waitExit(child: ChildProcess, timeoutMs: number): Promise<boolean> {
  if (exited(child)) return Promise.resolve(true);
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), timeoutMs);
    child.once('exit', () => {
      clearTimeout(timer);
      resolve(true);
    });
  });
}

/**
 * The Python server (server/main.py) as a child process. It serves the web
 * interface and the WebSocket on a free port of 127.0.0.1 and stops in order
 * when its standard input closes: on stop() and when this process dies.
 */
export class Backend {
  #options: BackendOptions;
  #child: ChildProcess | null = null;
  #port: number | null = null;
  #stopping = false;

  constructor(options: BackendOptions) {
    this.#options = options;
  }

  /** http://127.0.0.1:<port>, while the server runs. */
  get origin(): string {
    if (this.#port === null) throw new BackendError('The server is not running');
    return `http://${HOST}:${this.#port}`;
  }

  /** Resolves when the server answers; rejects with BackendError if it cannot start. */
  async start(): Promise<void> {
    if (this.#child) throw new BackendError('The server is already running');
    this.#stopping = false;
    let failure = new BackendError('The server did not start');
    for (let attempt = 1; attempt <= START_ATTEMPTS; attempt += 1) {
      const port = await freePort();
      const child = this.#spawn(port);
      if (child.pid === undefined) {
        throw new BackendError(`Cannot run the server: ${this.#options.python} is missing`);
      }
      const result = await this.#waitReady(child, port);
      if (result === 'ready') {
        this.#child = child;
        this.#port = port;
        child.once('exit', (code) => this.#onExit(child, code));
        return;
      }
      if (result === 'timeout') {
        await this.#terminate(child);
        throw new BackendError(`The server did not start in ${READY_TIMEOUT_MS / 1000} seconds`);
      }
      if (this.#stopping) throw new BackendError('The server was stopped while starting');
      failure = new BackendError(`The server exited with code ${child.exitCode ?? '?'}`);
    }
    throw failure;
  }

  /** Stop the server in order; safe to call twice and before start(). */
  async stop(): Promise<void> {
    this.#stopping = true;
    const child = this.#child;
    if (!child) return;
    await this.#terminate(child);
    this.#child = null;
    this.#port = null;
  }

  #spawn(port: number): ChildProcess {
    const { python, directory, data, log } = this.#options;
    const environment: NodeJS.ProcessEnv = {
      ...process.env,
      XPR_UI_HOST: HOST,
      XPR_UI_PORT: String(port),
      XPR_DATA_DIR: data,
      XPR_STOP_ON_STDIN_CLOSE: '1',
    };
    // Not for a child that is not Electron.
    delete environment.ELECTRON_RUN_AS_NODE;
    log.write(`\n--- Starting the server on ${HOST}:${port}\n`);
    const child = spawn(
      python,
      // -E, -s: only this Python and its packages, whatever the user's environment says;
      // -B: the installed application is read-only; -u: the log is written at once.
      ['-E', '-s', '-B', '-u', '-X', 'utf8', '-m', 'server.main'],
      {
        cwd: directory,
        env: environment,
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
      },
    );
    child.stdout?.on('data', (chunk: Buffer) => log.write(chunk));
    child.stderr?.on('data', (chunk: Buffer) => log.write(chunk));
    // Writing to a server that has exited must not throw.
    child.stdin?.on('error', () => {});
    child.on('error', (error) => log.write(`Cannot run ${python}: ${error.message}\n`));
    return child;
  }

  async #waitReady(child: ChildProcess, port: number): Promise<'ready' | 'exited' | 'timeout'> {
    const failed = new Promise<void>((resolve) => {
      child.once('exit', () => resolve());
      child.once('error', () => resolve());
    });
    const deadline = Date.now() + READY_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (exited(child)) return 'exited';
      if (await listening(port)) return 'ready';
      const stopped = await Promise.race([
        failed.then(() => true),
        new Promise<boolean>((resolve) => setTimeout(() => resolve(false), READY_POLL_MS)),
      ]);
      if (stopped) return 'exited';
    }
    return 'timeout';
  }

  async #terminate(child: ChildProcess): Promise<void> {
    if (exited(child) || child.pid === undefined) return;
    child.stdin?.end();
    if (await waitExit(child, STOP_TIMEOUT_MS)) return;
    this.#options.log.write('The server did not stop in time, terminating it\n');
    child.kill();
    if (await waitExit(child, KILL_TIMEOUT_MS)) return;
    child.kill('SIGKILL');
    await waitExit(child, KILL_TIMEOUT_MS);
  }

  #onExit(child: ChildProcess, code: number | null): void {
    if (this.#child !== child) return;
    this.#child = null;
    this.#port = null;
    this.#options.log.write(`--- The server exited with code ${code ?? '?'}\n`);
    if (!this.#stopping) this.#options.onExit(code);
  }
}
