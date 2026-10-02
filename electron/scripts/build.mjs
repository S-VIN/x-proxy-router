// Bundles the main process into dist/main.cjs. The modules shared with the web
// interface (the logo's states, the protocol types) are compiled into the bundle.
import { build } from 'esbuild';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

await build({
  entryPoints: [path.join(root, 'src', 'main.ts')],
  outfile: path.join(root, 'dist', 'main.cjs'),
  bundle: true,
  platform: 'node',
  target: 'node22',
  format: 'cjs',
  external: ['electron'],
  sourcemap: true,
  logLevel: 'info',
});
