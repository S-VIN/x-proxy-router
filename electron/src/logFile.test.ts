import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { LogFile } from './logFile';

let directory: string;

beforeEach(() => {
  directory = fs.mkdtempSync(path.join(os.tmpdir(), 'xpr-log-'));
});

afterEach(() => {
  fs.rmSync(directory, { recursive: true, force: true });
});

describe('LogFile', () => {
  it('creates its folder and appends', () => {
    const file = path.join(directory, 'logs', 'server.log');
    const first = new LogFile(file);
    first.write('one\n');
    first.close();
    const second = new LogFile(file);
    second.write(Buffer.from('two\n'));
    second.close();
    expect(fs.readFileSync(file, 'utf8')).toBe('one\ntwo\n');
  });

  it('starts a new file at the limit and keeps one previous', () => {
    const file = path.join(directory, 'server.log');
    const log = new LogFile(file, 10);
    log.write('aaaaaa\n');
    log.write('bbbbbb\n');
    expect(fs.readFileSync(`${file}.1`, 'utf8')).toBe('aaaaaa\n');
    expect(fs.readFileSync(file, 'utf8')).toBe('bbbbbb\n');
    log.write('cccccc\n');
    expect(fs.readFileSync(`${file}.1`, 'utf8')).toBe('bbbbbb\n');
    expect(fs.readFileSync(file, 'utf8')).toBe('cccccc\n');
    log.close();
    // A file left full by the previous run is not appended to.
    const next = new LogFile(file, 5);
    next.write('d\n');
    next.close();
    expect(fs.readFileSync(`${file}.1`, 'utf8')).toBe('cccccc\n');
    expect(fs.readFileSync(file, 'utf8')).toBe('d\n');
  });

  it('remembers the last complete lines', () => {
    const log = new LogFile(path.join(directory, 'server.log'));
    log.write('first\nsec');
    expect(log.tail).toBe('first');
    log.write('ond\r\n\n');
    expect(log.tail).toBe('first\nsecond');
    for (let line = 0; line < 100; line += 1) log.write(`line ${line}\n`);
    log.close();
    expect(log.tail.split('\n')).toHaveLength(40);
    expect(log.tail.endsWith('line 99')).toBe(true);
  });

  it('keeps the tail when the file cannot be written', () => {
    const blocked = path.join(directory, 'file');
    fs.writeFileSync(blocked, '');
    const log = new LogFile(path.join(blocked, 'server.log'));
    log.write('lost\n');
    expect(log.tail).toBe('lost');
  });
});
