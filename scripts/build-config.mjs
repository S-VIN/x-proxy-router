// The variables of the packages of every platform are in build.json (README.md); the
// versions of what the builds use stay with the code that uses it. This module adds the
// values made of the variables and gives both to the electron-builder configuration and
// to the main process of the desktop application. Run as a script, it prints them for
// the workflows: node scripts/build-config.mjs github >> "$GITHUB_OUTPUT".
import build from '../build.json' with { type: 'json' };

export { build };
export const { name, productName, version, description, author, license, repository } = build;

const [owner, project] = new URL(repository).pathname.split('/').filter(Boolean);

/**
 * io.github.<owner>.<project>, as Flathub names the applications of GitHub projects.
 * It names the Flatpak, the bundle of macOS, the application of Windows and the
 * autostart entries, so another repository moves them.
 */
export const appId = ['io', 'github', owner, project]
  .map((part) => part.toLowerCase().replace(/[^a-z0-9]/g, '_'))
  .join('.');

export const copyright = `Copyright © ${new Date().getFullYear()} ${author}`;

/** The systems of build.json: as electron-builder names them, and for people. */
const SYSTEMS = {
  linux: ['linux', 'Linux'],
  windows: ['win', 'Windows'],
  macos: ['mac', 'macOS'],
};

/** A job of the "Desktop application" workflow per system and architecture of its runners. */
export function desktopJobs() {
  return Object.entries(SYSTEMS).flatMap(([system, [os, label]]) =>
    Object.entries(build[system].runners).map(([arch, runner]) => {
      // electron-builder adds the architecture to its folders except for x64.
      const suffix = arch === 'x64' ? '' : `-${arch}`;
      return {
        name: `${label} ${arch}`,
        runner,
        os,
        arch,
        unpacked: os === 'mac' ? `mac${suffix}` : `${os}${suffix}-unpacked`,
      };
    }),
  );
}

/** The Docker image is built for the architectures of the Linux packages. */
export function dockerPlatforms() {
  return Object.keys(build.linux.runners).map((arch) => `linux/${arch === 'x64' ? 'amd64' : arch}`);
}

if (/build-config\.mjs$/.test(process.argv[1] ?? '') && process.argv[2] === 'github') {
  const outputs = {
    name,
    product_name: productName,
    app_id: appId,
    jobs: JSON.stringify(desktopJobs()),
    docker_platforms: dockerPlatforms().join(','),
  };
  for (const [key, value] of Object.entries(outputs)) console.log(`${key}=${value}`);
}
