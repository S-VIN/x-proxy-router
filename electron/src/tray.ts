import { Menu, Tray, nativeImage } from 'electron';
import { execFile } from 'node:child_process';
import path from 'node:path';
import type { LinkState } from '../../web/src/lib/linkState';
import { APP_NAME, type Autostart } from './autostart';
import type { Link } from './linkWatcher';

export interface AppTrayOptions {
  /** The folder with tray/<state>.png, made by scripts/make-icons.mjs. */
  assets: string;
  autostart: Autostart;
  onOpen: () => void;
  onQuit: () => void;
}

/**
 * Whether the desktop shows tray icons. Windows always does; on Linux a
 * StatusNotifier host must run: GNOME has none without an extension.
 */
export function trayAvailable(): Promise<boolean> {
  if (process.platform !== 'linux') return Promise.resolve(true);
  return new Promise((resolve) => {
    execFile(
      'gdbus',
      [
        'call',
        '--session',
        '--dest=org.freedesktop.DBus',
        '--object-path=/org/freedesktop/DBus',
        '--method=org.freedesktop.DBus.NameHasOwner',
        'org.kde.StatusNotifierWatcher',
      ],
      { timeout: 2000 },
      // Unknown (no gdbus, no session bus) counts as shown: the icon is made anyway.
      (error, stdout) => resolve(error ? true : stdout.includes('true')),
    );
  });
}

/**
 * The logo in the color of the state. Windows picks the @1.25x … @3x files next
 * to the 16 px one; Linux hosts scale one large icon.
 */
export function trayImage(assets: string, state: LinkState): Electron.NativeImage {
  const name = process.platform === 'win32' ? `${state}.png` : `${state}-large.png`;
  return nativeImage.createFromPath(path.join(assets, 'tray', name));
}

/**
 * The tray icon: colored by the state of the proxy connection like the logo of
 * the web interface, with the menu of the application.
 */
export class AppTray {
  #options: AppTrayOptions;
  #tray: Tray;
  #state: LinkState = 'none';

  constructor(options: AppTrayOptions) {
    this.#options = options;
    this.#tray = new Tray(trayImage(options.assets, 'none'));
    this.#tray.on('click', options.onOpen);
    this.#updateMenu();
  }

  setLink(link: Link): void {
    if (link.state !== this.#state) {
      this.#state = link.state;
      this.#tray.setImage(trayImage(this.#options.assets, link.state));
    }
    this.#tray.setToolTip(`${APP_NAME}: ${link.description}`);
  }

  destroy(): void {
    this.#tray.destroy();
  }

  #updateMenu(): void {
    const { autostart, onOpen, onQuit } = this.#options;
    let launchAtLogin = false;
    try {
      launchAtLogin = autostart.isEnabled();
    } catch {
      // Shown off when the system does not tell.
    }
    this.#tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: `Open ${APP_NAME}`, click: onOpen },
        { type: 'separator' },
        {
          label: 'Launch at login',
          type: 'checkbox',
          checked: launchAtLogin,
          click: (item) => {
            try {
              autostart.setEnabled(item.checked);
            } catch {
              // The menu below shows what the system has.
            }
            // Linux shows a changed menu only when it is set again.
            this.#updateMenu();
          },
        },
        { type: 'separator' },
        { label: 'Quit', click: onQuit },
      ]),
    );
  }
}
