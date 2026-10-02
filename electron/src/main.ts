import { BrowserWindow, Menu, app, dialog, shell } from 'electron';
import path from 'node:path';
import { APP_ID, APP_NAME, HIDDEN_FLAG, createAutostart } from './autostart';
import { Backend, BackendError } from './backend';
import { LinkWatcher } from './linkWatcher';
import { LogFile } from './logFile';
import { setupPaths } from './paths';
import { AppTray, trayAvailable, trayImage } from './tray';
import { MainWindow } from './window';

/** Started by the build to check a packaged application; see smokeTest(). */
const SMOKE_TEST_FLAG = '--smoke-test';
const SMOKE_TEST_TIMEOUT_MS = 90_000;
/** Lines of the server's log shown when it fails. */
const FAILURE_LOG_LINES = 12;

const paths = setupPaths();
const log = new LogFile(path.join(paths.logs, 'server.log'));
const autostart = createAutostart();
const mainWindow = new MainWindow({
  title: APP_NAME,
  icon: process.platform === 'linux' ? path.join(paths.assets, 'icon.png') : undefined,
  stateFile: path.join(app.getPath('userData'), 'window.json'),
});
const backend = new Backend({
  python: paths.python,
  directory: paths.backend,
  data: paths.data,
  log,
  onExit: (code) => void serverExited(code),
});

let tray: AppTray | null = null;
let watcher: LinkWatcher | null = null;
/** The server is being stopped before exit, or already is. */
let stopping: Promise<void> | null = null;
let stopped = false;

function webSocketUrl(origin: string): string {
  return `${origin.replace(/^http/, 'ws')}/ws`;
}

/** Follow the server at its current address; the tray icon shows the state. */
function watchLink(): void {
  watcher?.stop();
  watcher = new LinkWatcher(webSocketUrl(backend.origin), (link) => tray?.setLink(link));
  watcher.start();
}

function showWindow(minimized = false): void {
  if (stopping) return;
  try {
    mainWindow.show(backend.origin, minimized);
  } catch {
    // The server is starting or restarting: the window opens when it is ready.
    return;
  }
  // macOS: the Dock shows the application while it has a window, the menu bar always.
  void app.dock?.show();
}

/**
 * Windows and Linux: no menu bar, the interface is the whole application. macOS
 * has its menus at the top of the screen, and without them Cmd+C, Cmd+V, Cmd+W
 * and Cmd+Q do nothing.
 */
function applicationMenu(): Menu | null {
  if (process.platform !== 'darwin') return null;
  return Menu.buildFromTemplate([
    { role: 'appMenu' },
    { role: 'fileMenu' },
    { role: 'editMenu' },
    { role: 'windowMenu' },
  ]);
}

function logTail(): string {
  return log.tail.split('\n').slice(-FAILURE_LOG_LINES).join('\n');
}

/** Tell why the server does not run. Returns true when the user chose to try again. */
async function showFailure(message: string, retry: string): Promise<boolean> {
  const { response } = await dialog.showMessageBox({
    type: 'error',
    title: APP_NAME,
    message,
    detail: `${logTail()}\n\nLog: ${log.path}`,
    buttons: [retry, 'Show log', 'Quit'],
    defaultId: 0,
    cancelId: 2,
    noLink: true,
  });
  if (response === 1) shell.showItemInFolder(log.path);
  return response === 0;
}

/** Start the server; on a failure the user retries or the application exits. */
async function startServer(): Promise<boolean> {
  for (;;) {
    try {
      await backend.start();
      return true;
    } catch (error) {
      if (stopping) return false;
      const reason = error instanceof BackendError ? error.message : String(error);
      if (!(await showFailure(`The server could not start. ${reason}`, 'Try again'))) return false;
    }
  }
}

async function serverExited(code: number | null): Promise<void> {
  watcher?.stop();
  const restart = await showFailure(
    `The server stopped unexpectedly with code ${code ?? '?'}.`,
    'Restart',
  );
  if (!restart || !(await startServer())) {
    app.quit();
    return;
  }
  watchLink();
  mainWindow.reload(backend.origin);
}

async function start(): Promise<void> {
  Menu.setApplicationMenu(applicationMenu());
  const hidden = process.argv.includes(HIDDEN_FLAG);
  if (hidden) app.dock?.hide();
  if (!(await startServer())) {
    app.quit();
    return;
  }
  tray = new AppTray({
    assets: paths.assets,
    autostart,
    onOpen: () => showWindow(),
    onQuit: () => app.quit(),
  });
  watchLink();
  try {
    autostart.refresh();
  } catch {
    // The entry stays as it is; the tray menu can replace it.
  }
  // Started at login: only the tray icon. Without a tray the window is the only way in.
  if (!hidden) showWindow();
  else if (!(await trayAvailable())) showWindow(true);
}

/** Stop the server in order before the process exits; the window and the icon go at once. */
function stopBeforeQuit(event: Electron.Event): void {
  if (stopped) return;
  event.preventDefault();
  if (stopping) return;
  watcher?.stop();
  mainWindow.destroy();
  tray?.destroy();
  tray = null;
  stopping = backend.stop().finally(() => {
    stopped = true;
    log.close();
    app.quit();
  });
}

/**
 * Check of a packaged application, run by the build: the server starts with its
 * Python and core, serves the interface, the page draws itself and connects, the
 * tray icons load. Exits with 0, or 1 and the server's log.
 */
async function smokeTest(): Promise<void> {
  const fail = async (reason: string): Promise<never> => {
    console.error(`Smoke test failed: ${reason}\n${log.tail}`);
    // A Windows application has no console: the reason is read from the log.
    log.write(`--- Smoke test failed: ${reason}\n`);
    await backend.stop();
    app.exit(1);
    return new Promise(() => {});
  };
  const timer = setTimeout(() => void fail('timeout'), SMOKE_TEST_TIMEOUT_MS);
  try {
    await backend.start();
    let online = false;
    const link = new LinkWatcher(webSocketUrl(backend.origin), () => {
      online ||= link.link.state !== 'failed';
    });
    link.start();
    const window = new BrowserWindow({ show: false, webPreferences: { sandbox: true } });
    await window.loadURL(backend.origin);
    // The server sent its data over the WebSocket and the page has drawn its blocks.
    const drawn = `document.querySelectorAll('#app *').length > 20`;
    while (!online || !(await window.webContents.executeJavaScript(drawn))) {
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    link.stop();
    for (const state of ['none', 'working', 'failed'] as const) {
      if (trayImage(paths.assets, state).isEmpty()) await fail(`no tray icon for ${state}`);
    }
    window.destroy();
    await backend.stop();
    clearTimeout(timer);
    console.log('Smoke test passed');
    app.exit(0);
  } catch (error) {
    await fail(error instanceof Error ? error.message : String(error));
  }
}

/**
 * Chromium's processes take most of the memory, not the interface (README.md):
 * - the page is drawn without the GPU: it looks the same, and the GPU process loads
 *   no graphics driver, which was most of its memory;
 * - the network service, which here only loads the page from the local server, runs
 *   in the main process instead of a process of its own.
 */
function saveMemory(): void {
  app.disableHardwareAcceleration();
  app.commandLine.appendSwitch('enable-features', 'NetworkServiceInProcess2');
}

if (process.platform === 'win32') app.setAppUserModelId(APP_ID);
saveMemory();

if (process.argv.includes(SMOKE_TEST_FLAG)) {
  // Without a listener Electron quits when the test closes its window.
  app.on('window-all-closed', () => {});
  void app.whenReady().then(smokeTest);
} else if (!app.requestSingleInstanceLock()) {
  // The running application shows its window: see second-instance below.
  app.quit();
} else {
  app.on('second-instance', () => showWindow());
  // macOS: the application was opened again while it runs, or its Dock icon was clicked.
  app.on('activate', (_event, hasVisibleWindows) => {
    if (!hasVisibleWindows) showWindow();
  });
  // Closing the window leaves the application in the tray; without a tray it exits.
  app.on('window-all-closed', () => {
    app.dock?.hide();
    void trayAvailable().then((available) => {
      if (!available) app.quit();
    });
  });
  app.on('before-quit', stopBeforeQuit);
  void app.whenReady().then(start);
}
