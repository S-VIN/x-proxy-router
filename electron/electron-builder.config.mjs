// Packages of the desktop application; the "Desktop application" workflow runs
// electron-builder on a computer of each OS and architecture (README.md). The names,
// the version and the other variables come from build.json in the root.
import {
  appId,
  author,
  build,
  copyright,
  description,
  license,
  name,
  productName,
  repository,
  version,
} from '../scripts/build-config.mjs';

/** Every package is named <name>-<version>-<system>-<arch>; ${…} are electron-builder's. */
const artifactName = (system, ending = '.${ext}') =>
  `\${name}-\${version}-${system}-\${arch}${ending}`;

export default {
  appId,
  copyright,
  // Written into the package.json of the application, where electron-builder and
  // Electron find them.
  extraMetadata: {
    name,
    productName,
    version,
    description,
    author,
    license,
    homepage: repository,
    repository,
    // The desktop entry is named after it, and Electron uses it as the window's
    // application id: the desktop then shows the icon of the entry.
    desktopName: `${appId}.desktop`,
  },

  directories: {
    output: 'release',
    buildResources: 'build',
  },

  // dist: the bundled main process and the icons it loads (npm run build, npm run icons).
  files: ['dist/main.cjs', 'dist/assets/**', 'package.json'],
  asar: true,

  // The server with its Python and the core of the target platform
  // (scripts/prepare-backend.py): process.resourcesPath/backend.
  extraResources: [{ from: 'build/backend/${os}-${arch}', to: 'backend' }],

  win: {
    target: ['nsis', 'portable'],
    icon: 'build/icon.png',
  },

  nsis: {
    oneClick: build.windows.oneClick,
    perMachine: build.windows.perMachine,
    // With the settings it also removes the autostart entry (installer.nsh).
    deleteAppDataOnUninstall: build.windows.deleteAppDataOnUninstall,
    include: 'installer.nsh',
    artifactName: artifactName('windows', '-setup.${ext}'),
  },

  // One exe that runs without installation and keeps its data next to itself.
  portable: {
    artifactName: artifactName('windows', '-portable.${ext}'),
  },

  mac: {
    target: ['dmg'],
    icon: 'build/icon.png',
    category: build.macos.category,
    // "-": an ad-hoc signature, without which a Mac with Apple silicon does not run the
    // code at all; a downloaded application still has to be allowed by the user
    // (README.md).
    identity: build.macos.identity,
    // Serves notarization; with an ad-hoc signature it stops Electron and Python from
    // loading their libraries.
    hardenedRuntime: build.macos.identity !== '-',
    // Of the server only the executable files are signed: Python, its extension modules
    // and the core. The rest, thousands of files, is covered by the signature of the
    // application like any resource.
    signIgnore: ['/Contents/Resources/backend/(?!.*(\\.so|\\.dylib|/bin/python[^/]*|/mihomo)$)'],
  },

  // The application to drag into Applications.
  dmg: {
    artifactName: artifactName('macos'),
    // No updates: no file that describes the image for them.
    writeUpdateInfo: false,
  },

  linux: {
    target: ['AppImage', 'flatpak', 'pacman'],
    executableName: name,
    syncDesktopName: true,
    icon: 'build/icons',
    category: build.linux.category,
    artifactName: artifactName('linux'),
  },

  flatpak: {
    // The runtime the Electron base application is made for, of one version.
    runtime: 'org.freedesktop.Platform',
    runtimeVersion: build.linux.flatpak.version,
    sdk: 'org.freedesktop.Sdk',
    base: 'org.electronjs.Electron2.BaseApp',
    baseVersion: build.linux.flatpak.version,
    finishArgs: build.linux.flatpak.permissions,
  },

  // The package of Arch Linux and the distributions based on it: pacman -U installs it in
  // /opt with a command and a menu entry, and the libraries it needs.
  pacman: {
    artifactName: artifactName('linux', '.pkg.tar.zst'),
    compression: 'zstd',
    // The packager field of the package; electron-builder takes it from an author's email.
    maintainer: author,
    // The first line of the description of the package; electron-builder has a separate one.
    synopsis: description,
    // No updates: pacman updates the package; no file that describes it for them.
    publish: null,
    depends: build.linux.pacman.depends,
  },
};
