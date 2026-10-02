// Renders the logo of the web interface (web/src/lib/logo.ts) into the icons of
// the application, so both show the same picture and the same state colors:
//   dist/assets  - loaded by the running application: the tray and the window;
//   build        - taken by electron-builder: the executable, the installer, the packages.
import { Resvg } from '@resvg/resvg-js';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { logoSvg } from '../../web/src/lib/logo.ts';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const assets = path.join(root, 'dist', 'assets');
const build = path.join(root, 'build');

// The tray icon of Windows is 16 px at 100% scale; Electron takes the file of the
// display's scale by its suffix. Linux tray hosts scale one large picture.
const TRAY_SCALES = { '': 16, '@1.25x': 20, '@1.5x': 24, '@2x': 32, '@3x': 48 };
const TRAY_LARGE = 64;
// The menu bar of macOS shows the picture as it is: 20 points, the logo itself 16.
const TRAY_MAC_SCALES = { '': 20, '@2x': 40 };
// Sizes of an icon theme; electron-builder also makes the Windows and macOS icons from
// the largest. The logo has the margins macOS expects of an icon.
const APP_SIZES = [16, 24, 32, 48, 64, 128, 256, 512];

function render(state, size) {
  return new Resvg(logoSvg(state), { fitTo: { mode: 'width', value: size } }).render().asPng();
}

function write(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, data);
}

for (const state of ['none', 'working', 'failed']) {
  for (const [suffix, size] of Object.entries(TRAY_SCALES)) {
    write(path.join(assets, 'tray', `${state}${suffix}.png`), render(state, size));
  }
  write(path.join(assets, 'tray', `${state}-large.png`), render(state, TRAY_LARGE));
  for (const [suffix, size] of Object.entries(TRAY_MAC_SCALES)) {
    write(path.join(assets, 'tray', `${state}-mac${suffix}.png`), render(state, size));
  }
}

// The application itself is blue: the logo with no server connected.
write(path.join(assets, 'icon.png'), render('none', 256));
write(path.join(build, 'icon.png'), render('none', 1024));
for (const size of APP_SIZES) {
  write(path.join(build, 'icons', `${size}x${size}.png`), render('none', size));
}
console.log(`Icons written to ${path.relative(root, assets)} and ${path.relative(root, build)}`);
