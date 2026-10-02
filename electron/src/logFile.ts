import fs from 'node:fs';
import path from 'node:path';

/** The core logs every connection, so the log of an always running application is cut. */
const MAX_BYTES = 5 * 1024 * 1024;
const TAIL_LINES = 40;

/**
 * A log file that never grows over the limit: the full file becomes "<name>.1"
 * (replacing the previous one) and a new one starts. Remembers the last lines
 * to show them when the server fails.
 */
export class LogFile {
  readonly path: string;
  #maxBytes: number;
  #descriptor: number | null = null;
  #size = 0;
  #tail: string[] = [];
  #partial = '';

  constructor(file: string, maxBytes = MAX_BYTES) {
    this.path = file;
    this.#maxBytes = maxBytes;
  }

  /** The last complete lines written. */
  get tail(): string {
    return this.#tail.join('\n');
  }

  write(chunk: Buffer | string): void {
    const data = typeof chunk === 'string' ? Buffer.from(chunk) : chunk;
    this.#remember(data.toString('utf8'));
    try {
      if (this.#descriptor !== null && this.#size + data.length > this.#maxBytes) this.#rotate();
      if (this.#descriptor === null) this.#open();
      if (this.#descriptor === null) return;
      fs.writeSync(this.#descriptor, data);
      this.#size += data.length;
    } catch {
      // A full disk or a removed folder must not stop the application; the tail is kept.
      this.close();
    }
  }

  close(): void {
    if (this.#descriptor === null) return;
    try {
      fs.closeSync(this.#descriptor);
    } catch {
      // Nothing to do with a file that cannot be closed.
    }
    this.#descriptor = null;
  }

  #open(): void {
    fs.mkdirSync(path.dirname(this.path), { recursive: true });
    this.#descriptor = fs.openSync(this.path, 'a');
    this.#size = fs.fstatSync(this.#descriptor).size;
    if (this.#size >= this.#maxBytes) this.#rotate();
  }

  #rotate(): void {
    this.close();
    fs.renameSync(this.path, `${this.path}.1`);
    this.#descriptor = fs.openSync(this.path, 'a');
    this.#size = 0;
  }

  #remember(text: string): void {
    const lines = (this.#partial + text).split(/\r?\n/);
    this.#partial = lines.pop() ?? '';
    this.#tail.push(...lines.filter((line) => line.trim() !== ''));
    if (this.#tail.length > TAIL_LINES) this.#tail.splice(0, this.#tail.length - TAIL_LINES);
  }
}
