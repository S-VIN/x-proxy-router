import { BrowserWindow, type Rectangle, app, screen, session, shell } from 'electron';
import fs from 'node:fs';

const DEFAULT_SIZE = { width: 1180, height: 780 };
/** The interface moves its side blocks under the center one in a narrow window. */
const MIN_SIZE = { width: 380, height: 420 };
/**
 * The interface keeps nothing in the browser, and its address changes with every
 * start: a session in memory leaves no cache of each address on the disk.
 */
const PARTITION = 'interface';
/** --color-bg of the interface (web/src/styles/tokens.css), shown until its page is drawn. */
const BACKGROUND = '#fafafb';

interface WindowState {
  bounds?: Rectangle;
  maximized?: boolean;
}

export interface MainWindowOptions {
  title: string;
  /** Window icon; Windows takes it from the executable. */
  icon?: string;
  /** Where the size and position are remembered. */
  stateFile: string;
}

function readState(file: string): WindowState {
  try {
    const state = JSON.parse(fs.readFileSync(file, 'utf8')) as WindowState;
    const bounds = state.bounds;
    const numbers = bounds && [bounds.x, bounds.y, bounds.width, bounds.height];
    if (!numbers || !numbers.every((value) => Number.isFinite(value))) return {};
    // A window remembered on a display that is gone would open out of sight.
    const visible = screen.getAllDisplays().some(({ workArea }) => {
      const width =
        Math.min(bounds.x + bounds.width, workArea.x + workArea.width) -
        Math.max(bounds.x, workArea.x);
      const height =
        Math.min(bounds.y + bounds.height, workArea.y + workArea.height) -
        Math.max(bounds.y, workArea.y);
      return width >= 100 && height >= 100;
    });
    return visible ? { bounds, maximized: state.maximized === true } : {};
  } catch {
    return {};
  }
}

/**
 * The only window: the web interface served by the server. Closing destroys it,
 * the application stays in the tray; show() makes it again.
 */
export class MainWindow {
  #options: MainWindowOptions;
  #window: BrowserWindow | null = null;
  #origin = '';

  constructor(options: MainWindowOptions) {
    this.#options = options;
  }

  /** Open the interface at the origin of the server, or bring the open window forward. */
  show(origin: string, minimized = false): void {
    const existing = this.#window;
    if (existing) {
      if (origin !== this.#origin) {
        this.#origin = origin;
        void existing.loadURL(origin);
      }
      if (existing.isMinimized()) existing.restore();
      existing.show();
      existing.focus();
      return;
    }
    this.#origin = origin;
    const state = readState(this.#options.stateFile);
    const window = new BrowserWindow({
      ...DEFAULT_SIZE,
      ...state.bounds,
      minWidth: MIN_SIZE.width,
      minHeight: MIN_SIZE.height,
      show: false,
      title: this.#options.title,
      icon: this.#options.icon,
      backgroundColor: BACKGROUND,
      autoHideMenuBar: true,
      webPreferences: {
        session: interfaceSession(),
        contextIsolation: true,
        sandbox: true,
        nodeIntegration: false,
        spellcheck: false,
      },
    });
    this.#window = window;
    if (state.maximized) window.maximize();

    window.once('ready-to-show', () => {
      if (minimized) window.minimize();
      else window.show();
    });
    // The page names itself x-proxy-router; the window keeps the name of the application.
    window.on('page-title-updated', (event) => event.preventDefault());
    window.on('close', () => this.#saveState(window));
    window.on('closed', () => {
      if (this.#window === window) this.#window = null;
    });

    const contents = window.webContents;
    // Only the interface lives in the window: other pages open in the browser.
    contents.setWindowOpenHandler(({ url }) => {
      openExternal(url);
      return { action: 'deny' };
    });
    contents.on('will-navigate', (event, url) => {
      if (sameOrigin(url, this.#origin)) return;
      event.preventDefault();
      openExternal(url);
    });
    if (!app.isPackaged) {
      contents.on('before-input-event', (_event, input) => {
        if (input.type !== 'keyDown') return;
        if (input.key === 'F12') contents.toggleDevTools();
        if (input.key === 'F5') contents.reload();
      });
    }
    void window.loadURL(origin);
  }

  /** Show the interface of a restarted server in the open window. */
  reload(origin: string): void {
    this.#origin = origin;
    if (this.#window) void this.#window.loadURL(origin);
  }

  get isOpen(): boolean {
    return this.#window !== null;
  }

  destroy(): void {
    const window = this.#window;
    if (!window) return;
    this.#saveState(window);
    this.#window = null;
    window.destroy();
  }

  #saveState(window: BrowserWindow): void {
    const state: WindowState = {
      bounds: window.getNormalBounds(),
      maximized: window.isMaximized(),
    };
    try {
      fs.writeFileSync(this.#options.stateFile, JSON.stringify(state));
    } catch {
      // The size is a convenience: without it the window opens with the default one.
    }
  }
}

function interfaceSession(): Electron.Session {
  const memory = session.fromPartition(PARTITION);
  // The interface asks for nothing: no camera, location or notifications.
  memory.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  return memory;
}

function sameOrigin(url: string, origin: string): boolean {
  try {
    return new URL(url).origin === origin;
  } catch {
    return false;
  }
}

function openExternal(url: string): void {
  try {
    const { protocol } = new URL(url);
    if (protocol === 'http:' || protocol === 'https:') void shell.openExternal(url);
  } catch {
    // Not a URL: nothing to open.
  }
}
