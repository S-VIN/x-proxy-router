import { describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({
  app: { isPackaged: true, getAppPath: () => '/app' },
}));

const { desktopEntry, launchCommand } = await import('./autostart');

describe('launchCommand', () => {
  it('starts what the user has, not what runs now', () => {
    expect(launchCommand({ FLATPAK_ID: 'io.github.s_vin.x_proxy_router' })).toEqual([
      'flatpak',
      'run',
      'io.github.s_vin.x_proxy_router',
      '--hidden',
    ]);
    expect(launchCommand({ APPIMAGE: '/home/me/Apps/X Proxy Router.AppImage' })).toEqual([
      '/home/me/Apps/X Proxy Router.AppImage',
      '--hidden',
    ]);
    expect(launchCommand({ PORTABLE_EXECUTABLE_FILE: 'D:\\x-proxy-router.exe' })).toEqual([
      'D:\\x-proxy-router.exe',
      '--hidden',
    ]);
    expect(launchCommand({})).toEqual([process.execPath, '--hidden']);
  });
});

describe('desktopEntry', () => {
  it('quotes the command for the Exec key', () => {
    const entry = desktopEntry(['/home/me/My Apps/x "1" $HOME 100%.AppImage', '--hidden']);
    expect(entry.split('\n')).toContain(
      'Exec="/home/me/My Apps/x \\"1\\" \\$HOME 100%%.AppImage" --hidden',
    );
    expect(entry).toMatch(/^\[Desktop Entry\]\nType=Application\nName=X Proxy Router\n/);
    expect(entry).not.toContain('X-Flatpak');
    expect(entry.endsWith('\n')).toBe(true);
  });

  it('names the Flatpak application', () => {
    const id = 'io.github.s_vin.x_proxy_router';
    const lines = desktopEntry(['flatpak', 'run', id, '--hidden'], id).split('\n');
    expect(lines).toContain(`Exec=flatpak run ${id} --hidden`);
    expect(lines).toContain(`Icon=${id}`);
    expect(lines).toContain(`X-Flatpak=${id}`);
  });
});
