import { app, dialog } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import { name, productName } from '../../scripts/build-config.mjs';

/**
 * Folder name in the user's application data: the name of the package, by which the
 * Windows uninstaller removes it.
 */
const DATA_FOLDER = name;

export interface Paths {
  /** settings.sqlite3 of the server, the logs and the window state. */
  data: string;
  /** The server's log. */
  logs: string;
  /** Holds server/, web/dist and resources/mihomo, as the repository does. */
  backend: string;
  /** The Python that runs the server. */
  python: string;
  /** Icons made from the logo (scripts/make-icons.mjs). */
  assets: string;
}

/**
 * Where the application keeps its data:
 * - XPR_DESKTOP_DATA_DIR, when set: for development and tests;
 * - the portable Windows build: data/ next to the exe, nothing is left on the computer;
 * - development: the repository, like the server started by hand (README.md);
 * - otherwise the user's application data: %APPDATA%\x-proxy-router,
 *   ~/Library/Application Support/x-proxy-router or ~/.config/x-proxy-router
 *   (~/.var/app/<id>/config/x-proxy-router in Flatpak).
 */
function dataDirectory(): string {
  const override = process.env.XPR_DESKTOP_DATA_DIR;
  if (override) return path.resolve(override);
  const portable = process.env.PORTABLE_EXECUTABLE_DIR;
  if (portable) return path.join(portable, 'data');
  if (!app.isPackaged) return path.resolve(__dirname, '..', '..');
  return path.join(app.getPath('appData'), DATA_FOLDER);
}

/** Electron keeps its own files with the data, the browser profile in its own folder. */
function electronDirectory(data: string): string {
  // The repository is not a place for Electron's files.
  if (!app.isPackaged && !process.env.XPR_DESKTOP_DATA_DIR) {
    return path.join(app.getPath('appData'), `${DATA_FOLDER}-dev`);
  }
  return data;
}

/** Call before the app is ready: Electron reads its folders once. */
export function setupPaths(): Paths {
  const data = dataDirectory();
  const electron = electronDirectory(data);
  const browser = path.join(electron, 'browser');
  try {
    fs.mkdirSync(data, { recursive: true });
    fs.mkdirSync(browser, { recursive: true });
  } catch (error) {
    // E.g. the portable exe on a read-only disk: nowhere to keep the settings.
    const reason = error instanceof Error ? error.message : String(error);
    dialog.showErrorBox(productName, `Cannot create the data folder ${data}.\n${reason}`);
    process.exit(1);
  }
  app.setPath('userData', electron);
  app.setPath('sessionData', browser);

  const windows = process.platform === 'win32';
  let backend: string;
  let python: string;
  if (app.isPackaged) {
    // Staged by scripts/prepare-backend.py and packed as extraResources.
    backend = path.join(process.resourcesPath, 'backend');
    python = windows
      ? path.join(backend, 'python', 'python.exe')
      : path.join(backend, 'python', 'bin', 'python3');
  } else {
    // The repository and its .venv (uv sync).
    backend = path.resolve(__dirname, '..', '..');
    python = windows
      ? path.join(backend, '.venv', 'Scripts', 'python.exe')
      : path.join(backend, '.venv', 'bin', 'python');
  }
  return {
    data,
    logs: path.join(electron, 'logs'),
    backend,
    python,
    assets: path.join(__dirname, 'assets'),
  };
}
