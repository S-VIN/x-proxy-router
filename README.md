# x-proxy-router

Проект приложения для запуска и настройки ядра Mihomo: серверная часть, затем веб-интерфейс
и десктопное приложение на Electron для Windows, Linux и macOS.

## Инструменты разработки

Требуются Python 3.11+ и [uv](https://docs.astral.sh/uv/).
Установка зависимостей сервера и инструментов в локальную `.venv`:

```sh
uv sync --locked
```

Проверки и форматирование из корня проекта:

```sh
uv run ruff check .
uv run ruff format --check .
uv run ty check

# Применить форматирование:
uv run ruff format .
```

Настройки находятся в `pyproject.toml`, точные версии — в `uv.lock`.
Ruff проверяет стиль и ошибки кода, ty — типы.
В существующем коде пока есть замечания обоих инструментов;
установка инструментов не применяет исправления автоматически.
Самодостаточные скрипты из `scripts` по-прежнему можно запускать обычным `python`.

## Бинарники Mihomo

Официальные сборки [Mihomo](https://github.com/MetaCubeX/mihomo) **v1.19.31**
находятся в [`resources/mihomo`](resources/mihomo), лицензия — в
[`resources/mihomo/LICENSE`](resources/mihomo/LICENSE).

| ОС | Архитектура | Исполняемый файл |
| --- | --- | --- |
| Linux | x86-64 / amd64 | `resources/mihomo/linux/x64/mihomo` |
| Linux | ARM64 / aarch64 | `resources/mihomo/linux/arm64/mihomo` |
| Windows | x86-64 / amd64 | `resources/mihomo/win32/x64/mihomo.exe` |
| Windows | ARM64 | `resources/mihomo/win32/arm64/mihomo.exe` |
| macOS | x86-64 / amd64 (Intel) | `resources/mihomo/darwin/x64/mihomo` |
| macOS | ARM64 (Apple silicon) | `resources/mihomo/darwin/arm64/mihomo` |

Для x86-64 используются сборки `compatible`, они работают и на старых процессорах.
Имена `linux`, `win32`, `darwin`, `x64`, `arm64` соответствуют значениям Node.js
`process.platform` и `process.arch`. Остальные ОС и архитектуры пока не включены.

### Повторное скачивание

Нужны Python 3.9+ и доступ к GitHub. Сторонние Python-пакеты не требуются.

```sh
python3 scripts/download-mihomo.py
```

На Windows используйте `py -3` вместо `python3`. Версия и SHA-256 архивов
закреплены в скрипте; он проверяет архив перед распаковкой, перезаписывает
бинарники и выставляет бинарникам Linux и macOS права `0755`. Для обновления версии
нужно обновить версию и SHA-256 в скрипте из официального релиза.

### Использование сервером, Docker и Electron

Сервер сам выбирает бинарник текущей платформы, запускает его с временным
конфигом и управляет им через локальный REST API.

Образ Docker (`docker/Dockerfile`) берёт только бинарник для архитектуры образа:
`amd64` → `linux/x64`, `arm64` → `linux/arm64`. Десктопное приложение так же получает
один бинарник своей платформы: `electron/scripts/prepare-backend.py` кладёт его вместе
с сервером в ресурсы приложения, вне `app.asar`.

## Серверная часть

Точка входа приложения — `server/main.py`. Сервер настраивается переменными
окружения; их задают десктопное приложение (Electron) и Docker
([`docker/README.md`](docker/README.md)):

| Переменная | Обязательна | Назначение |
| --- | --- | --- |
| `XPR_UI_PORT` | да | Порт веб-интерфейса и WebSocket. |
| `XPR_DATA_DIR` | да | Абсолютный путь к папке с `settings.sqlite3`; создаётся, если её нет. |
| `XPR_UI_HOST` | нет | IP-адрес веб-интерфейса, по умолчанию `0.0.0.0` — все IPv4-адреса компьютера. |
| `XPR_STOP_ON_STDIN_CLOSE` | нет | `1` — штатно остановиться, когда закроется стандартный ввод. Задаёт десктопное приложение. |

Если обязательной переменной нет или значение неверное, сервер не запускается и
называет её. Запуск для разработки — только на этом компьютере и с базой в корне
проекта:

```sh
uv sync --locked
XPR_UI_HOST=127.0.0.1 XPR_UI_PORT=20800 XPR_DATA_DIR="$PWD" uv run python -m server.main
```

В PowerShell переменные задаются отдельно: `$env:XPR_UI_PORT = "20800"` и т. д.

На старте создаются `SettingsStore`, клиент Mihomo и планировщик APScheduler,
запускается Mihomo (тестовый SOCKS5 на свободном порту `127.0.0.1`), он получает сохранённые
правила роутинга, в нём запускаются сохранённые inbound (по умолчанию
SOCKS5/HTTP-прокси `127.0.0.1:20808`) и регистрируются сохранённые серверы.
Хендлеры получают общий контекст и могут запускаться напрямую или по расписанию.
Клиенты подключаются по WebSocket к `ws://<XPR_UI_HOST>:<XPR_UI_PORT>/ws`,
при запуске выше — `ws://127.0.0.1:20800/ws`.

Сервер также раздаёт собранный веб-интерфейс из `web/dist`:
после сборки он открывается по адресу `http://127.0.0.1:20800/`.

Архитектура, регистрация хендлеров, изменение расписания и интерфейсы ядер:
[`server/README.md`](server/README.md).
Протокол между клиентами и сервером: [`server/PROTOCOL.md`](server/PROTOCOL.md).

## Переменные сборки

Переменные пакетов всех платформ — что это за приложение, его версия, под какие
системы и архитектуры оно собирается и как выглядят пакеты каждой системы — записаны в
одном файле [`build.json`](build.json). Его читает `scripts/build-config.mjs`: он
вычисляет из переменных остальные значения и отдаёт их конфигурации electron-builder
(`electron/electron-builder.config.mjs`), main-процессу приложения и workflow
(`node scripts/build-config.mjs github`).

| Переменная | Сейчас | На что влияет |
| --- | --- | --- |
| `name` | `x-proxy-router` | имена файлов пакетов и артефактов CI, команда и пакет pacman в Linux, папка данных (`%APPDATA%\x-proxy-router`, `~/.config/x-proxy-router`) |
| `productName` | `X Proxy Router` | имя в меню, окнах и трее, `X Proxy Router.exe` и `.app`, папка `/opt/X Proxy Router` |
| `version` | `0.1.0` | версия всех пакетов и их имён |
| `description` | одна строка | описание приложения в пакетах и в пункте меню Linux |
| `author` | `S-VIN` | автор и издатель, `Copyright © <год сборки> <author>`, packager пакета pacman |
| `license` | `MIT` | лицензия в пакетах |
| `repository` | `https://github.com/S-VIN/x-proxy-router` | домашняя страница пакетов и id приложения `io.github.<владелец>.<репозиторий>` (`io.github.s_vin.x_proxy_router`): id Flatpak, bundle macOS, AppUserModelID Windows, записи автозапуска |
| `windows.runners`, `macos.runners`, `linux.runners` | метка раннера GitHub на архитектуру | под какие архитектуры собирается каждая система — по заданию workflow «Desktop application» на каждую; образ Docker собирается под архитектуры Linux |
| `windows.oneClick`, `.perMachine`, `.deleteAppDataOnUninstall` | `true`, `false`, `true` | инсталлер: без вопросов, для текущего пользователя без прав администратора, удаление стирает настройки и автозапуск |
| `macos.category` | `public.app-category.utilities` | категория приложения |
| `macos.identity` | `-` | подпись: `-` — ad-hoc; имя сертификата Developer ID или `null` (найти самому) — настоящая, тогда включается hardened runtime |
| `linux.category` | `Network` | раздел меню |

Смена `name` или `repository` после выпуска переносит папку данных и id приложения: у
пользователей пропадут настройки и останутся старые записи автозапуска.

Зависимости и их версии в `build.json` не входят, они лежат рядом с тем, что их
использует:

| Что | Где |
| --- | --- |
| Electron, electron-builder и другие пакеты npm | `electron/package.json`, `web/package.json` и их `package-lock.json` |
| Пакеты Python сервера | `pyproject.toml` и `uv.lock`, `server/requirements.txt` |
| Python внутри десктопных пакетов | `electron/scripts/prepare-backend.py` |
| Mihomo | `scripts/download-mihomo.py` |
| Среда Flatpak, его права и библиотеки пакета pacman | `electron/electron-builder.config.mjs` |
| Node.js, uv и образы Docker | `.github/workflows/*.yml`, `docker/Dockerfile` |

## Docker

Для сервера приложение запускается в Docker: образ собирает workflow «Docker image» в
GitHub Actions (только вручную) и публикует в `ghcr.io/s-vin/x-proxy-router`, запуск —
через `docker/compose.yaml`. Сборка, переменные окружения, запуск и обновление:
[`docker/README.md`](docker/README.md).

## Десктопное приложение

Папка [`electron`](electron) — приложение для Windows, Linux и macOS (x64 и arm64):
запускает сервер с ядром и показывает веб-интерфейс в своём окне, при закрытии окна
остаётся в трее. Варианты: инсталлер и портативный exe для Windows, AppImage, Flatpak и
пакет pacman для Linux, образ DMG для macOS.
Их собирает workflow «Desktop application» в GitHub Actions (только вручную), файлы —
в артефактах запуска. Запуск для разработки:

```sh
uv sync --locked
(cd web && npm ci && npm run build)
cd electron && npm ci && npm run dev
```

Устройство, сборка пакетов и расположение данных: [`electron/README.md`](electron/README.md).

## Веб-интерфейс

Одностраничный клиент на Svelte 5 и TypeScript находится в папке `web`.
Нужен Node.js 20.19+ или 22.12+.

```sh
cd web
npm ci
npm run build      # собрать в web/dist, сервер раздаёт его на http://127.0.0.1:20800/
npm run dev        # dev-сервер Vite на http://localhost:5173, /ws проксируется на 127.0.0.1:20800
```

Страница подключается к `/ws` своего адреса; другой адрес WebSocket можно задать
при сборке переменной `VITE_WS_URL`, например `ws://127.0.0.1:20800/ws`.

Проверки:

```sh
npm run check         # типы (svelte-check)
npm test              # unit-тесты транспорта и хранилищ (vitest)
npm run format:check  # стиль (Prettier); npm run format — исправить
```

Данные приходят по протоколу из [`server/PROTOCOL.md`](server/PROTOCOL.md):
`src/lib/api` — WebSocket-соединение и типы сообщений, `src/lib/stores` — по хранилищу
на модель сервера, `src/lib/linkState.ts` и `src/lib/logo.ts` — состояние подключения и
логотип в его цвете (их же использует иконка трея десктопного приложения),
`src/components` — UI-примитивы (`ui`), каркас страницы (`layout`)
и блоки интерфейса (`blocks`). Цвета, отступы и шрифты заданы переменными в
`src/styles/tokens.css`.

У каждого типа inbound своя кнопка в блоке Inbounds, например «Add proxy»: она
открывает настройки нового inbound этого типа. Чтобы добавить тип, нужно:

- описать его в `INBOUND_TYPES` (по нему появляется кнопка) и `InboundDraft` в
  `src/lib/inbounds.ts` с проверками и полями запроса;
- сделать компонент настроек рядом с `ProxyFields`
  (`src/components/blocks/inbounds`);
- показать этот компонент в `InboundForm`.
