import { app } from 'electron';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

/** Started at login: no window, only the tray icon. */
export const HIDDEN_FLAG = '--hidden';

export const APP_NAME = 'X Proxy Router';
/**
 * The Flatpak application id, the Windows AppUserModelID, the label of the macOS
 * launch agent and the name of the icon.
 */
export const APP_ID = 'io.github.s_vin.x_proxy_router';
const DESKTOP_FILE = 'x-proxy-router.desktop';

export interface Autostart {
  isEnabled(): boolean;
  setEnabled(enabled: boolean): void;
  /** Point an enabled entry at this executable again, e.g. after the application was moved. */
  refresh(): void;
}

/** The command that starts this application, as the system has to run it at login. */
export function launchCommand(environment: NodeJS.ProcessEnv = process.env): string[] {
  // Inside the sandbox the executable has a path the host does not know.
  if (environment.FLATPAK_ID) return ['flatpak', 'run', environment.FLATPAK_ID, HIDDEN_FLAG];
  // The mounted image is gone after exit: the AppImage file itself is started.
  if (environment.APPIMAGE) return [environment.APPIMAGE, HIDDEN_FLAG];
  // The portable build runs unpacked in a temporary folder: the exe the user has is started.
  if (environment.PORTABLE_EXECUTABLE_FILE)
    return [environment.PORTABLE_EXECUTABLE_FILE, HIDDEN_FLAG];
  if (!app.isPackaged) return [process.execPath, app.getAppPath(), HIDDEN_FLAG];
  return [process.execPath, HIDDEN_FLAG];
}

/** An argument of the Exec key of a desktop entry (Desktop Entry Specification). */
function quoteExec(argument: string): string {
  if (/^[A-Za-z0-9_\-+,./:=@]+$/.test(argument)) return argument;
  return `"${argument.replace(/(["`$\\])/g, '\\$1').replace(/%/g, '%%')}"`;
}

/** The desktop entry that starts the command at login. */
export function desktopEntry(command: string[], flatpakId?: string): string {
  const lines = [
    '[Desktop Entry]',
    'Type=Application',
    `Name=${APP_NAME}`,
    'Comment=Start in the tray at login',
    `Exec=${command.map(quoteExec).join(' ')}`,
    `Icon=${flatpakId ?? 'x-proxy-router'}`,
    'Terminal=false',
    'X-GNOME-Autostart-enabled=true',
  ];
  if (flatpakId) lines.push(`X-Flatpak=${flatpakId}`);
  return `${lines.join('\n')}\n`;
}

/** The text of a property list string. */
function escapeXml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** The launch agent of macOS that starts the command at login. */
export function launchAgent(command: string[]): string {
  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
    '<plist version="1.0">',
    '<dict>',
    '  <key>Label</key>',
    `  <string>${APP_ID}</string>`,
    '  <key>ProgramArguments</key>',
    '  <array>',
    ...command.map((argument) => `    <string>${escapeXml(argument)}</string>`),
    '  </array>',
    '  <key>RunAtLoad</key>',
    '  <true/>',
    // An application the user works with, not a background job to slow down.
    '  <key>ProcessType</key>',
    '  <string>Interactive</string>',
    '</dict>',
    '</plist>',
  ];
  return `${lines.join('\n')}\n`;
}

/** An entry that is a file the system reads at login: it exists while autostart is on. */
function fileAutostart(file: string, entry: () => string): Autostart {
  const read = () => {
    try {
      return fs.readFileSync(file, 'utf8');
    } catch {
      return null;
    }
  };
  const write = () => {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, entry());
  };
  return {
    isEnabled: () => read() !== null,
    setEnabled(enabled) {
      if (enabled) write();
      else fs.rmSync(file, { force: true });
    },
    refresh() {
      const current = read();
      if (current !== null && current !== entry()) write();
    },
  };
}

/**
 * Linux has no API for it: a desktop entry in the autostart folder of the user.
 * Flatpak gives the application its own XDG_CONFIG_HOME, so there the folder of
 * the host is used (the package is allowed to write it).
 */
function linuxAutostart(): Autostart {
  const flatpakId = process.env.FLATPAK_ID;
  const config =
    !flatpakId && process.env.XDG_CONFIG_HOME
      ? process.env.XDG_CONFIG_HOME
      : path.join(os.homedir(), '.config');
  return fileAutostart(path.join(config, 'autostart', DESKTOP_FILE), () =>
    desktopEntry(launchCommand(), flatpakId),
  );
}

/**
 * macOS: a launch agent of the user, which launchd reads at login. The login
 * items of the system settings cannot pass --hidden to the application.
 */
function macAutostart(): Autostart {
  const file = path.join(os.homedir(), 'Library', 'LaunchAgents', `${APP_ID}.plist`);
  return fileAutostart(file, () => launchAgent(launchCommand()));
}

/**
 * Windows: a value of the Run key of the user, named after the AppUserModelID
 * (main.ts sets it to APP_ID); installer.nsh removes it on uninstall.
 */
function windowsAutostart(): Autostart {
  const [executable, ...args] = launchCommand();
  const options = { path: executable, args };
  return {
    // False as well when the entry was turned off in the Windows settings.
    isEnabled: () => app.getLoginItemSettings(options).executableWillLaunchAtLogin,
    setEnabled(enabled) {
      app.setLoginItemSettings({ ...options, openAtLogin: enabled, enabled: true });
    },
    // An entry of a moved portable exe matches nothing: the item is shown off and
    // turning it on replaces the entry.
    refresh() {},
  };
}

export function createAutostart(): Autostart {
  if (process.platform === 'win32') return windowsAutostart();
  if (process.platform === 'darwin') return macAutostart();
  return linuxAutostart();
}
