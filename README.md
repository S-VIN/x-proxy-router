# x-proxy-router

Проект приложения для запуска и настройки Xray: серверная часть, затем веб-интерфейс
и десктопное приложение на Electron для Windows и Linux.

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
Ruff проверяет стиль и ошибки кода, ty — типы. Сгенерированные файлы
`server/cores/xray/grpc_generated` исключены из проверок и форматирования.
В существующем коде пока есть замечания обоих инструментов;
установка инструментов не применяет исправления автоматически.
Самодостаточные скрипты из `scripts` по-прежнему можно запускать обычным `python`.

## Бинарники Xray

Официальные сборки Xray-core **v26.3.27** находятся в [`resources/xray`](resources/xray).
Версия, ссылки на архивы и их SHA-256 закреплены в
[`manifest.json`](resources/xray/manifest.json).

| ОС | Архитектура | Исполняемый файл |
| --- | --- | --- |
| Linux | x86-64 / amd64 | `resources/xray/linux/x64/xray` |
| Linux | ARM64 / aarch64 | `resources/xray/linux/arm64/xray` |
| Linux | ARMv7 (32 бита) | `resources/xray/linux/armv7/xray` |
| Windows | x86-64 / amd64 | `resources/xray/win32/x64/xray.exe` |
| Windows | ARM64 | `resources/xray/win32/arm64/xray.exe` |

Каждая папка содержит полный комплект из официального архива: исполняемый файл,
`geoip.dat`, `geosite.dat`, лицензию и README upstream. `checksums.json` содержит
SHA-256 распакованных файлов. Скрипт выставляет Linux-бинарникам права `0755`.

### Повторное скачивание

Нужны Python 3.9+ и доступ к GitHub. Сторонние Python-пакеты не требуются.

```sh
python3 scripts/download-xray.py
python3 scripts/download-xray.py --target linux/x64
python3 scripts/download-xray.py --target win32/x64 --target win32/arm64
```

На Windows используйте `py -3` вместо `python3`. Скрипт проверяет SHA-256 архива
по manifest перед распаковкой; повторный запуск перезаписывает файлы выбранных
комплектов. Для обновления версии нужно обновить URL и SHA-256 в manifest из
официального релиза, затем запустить скрипт.

### Использование сервером и Electron

Имена `linux`, `win32`, `x64`, `arm64` соответствуют значениям Node.js
`process.platform` и `process.arch`. Для ARMv7 значение Node.js — `arm`:
сервер должен дополнительно проверить версию ARM и выбрать `armv7`.
Остальные ОС и архитектуры пока не включены.

Запускайте Xray по абсолютному пути и передавайте конфигурацию явно:

```sh
./resources/xray/linux/x64/xray version
./resources/xray/linux/x64/xray run -test -config /absolute/path/config.json
./resources/xray/linux/x64/xray run -config /absolute/path/config.json
```

Задавайте `XRAY_LOCATION_ASSET` равным абсолютному пути к папке выбранного
комплекта для загрузки `geoip.dat` и `geosite.dat`. Генерируемую конфигурацию
и пользовательские данные храните отдельно от бинарников.

В Electron упаковывайте нужный комплект через `extraResources`, вне `app.asar`;
в установленном приложении стройте путь относительно `process.resourcesPath`.
Архитектуру выбирайте для целевой сборки приложения.

В Docker копируйте только комплект для целевой архитектуры образа:
`amd64` → `linux/x64`, `arm64` → `linux/arm64`, `arm/v7` → `linux/armv7`. После копирования задайте `chmod 755` для `xray` и
`XRAY_LOCATION_ASSET` для каталога комплекта. Полный набор всех платформ
не нужен внутри одного образа.

## Серверная часть

Точка входа приложения — `server/main.py`. Запуск:

```sh
uv sync --locked
uv run python -m server.main
```

На старте создаются `SettingsStore`, клиент Mihomo и планировщик APScheduler,
запускается Mihomo (тестовый SOCKS5 `127.0.0.1:20809`), в нём запускаются
сохранённые inbound (по умолчанию SOCKS5/HTTP-прокси `127.0.0.1:20808`)
и регистрируются сохранённые серверы.
Хендлеры получают общий контекст и могут запускаться напрямую или по расписанию.
Клиенты подключаются по WebSocket к `ws://127.0.0.1:20800/ws`.
БД `settings.sqlite3` создаётся в текущей рабочей папке.

Сервер также раздаёт собранный веб-интерфейс из `web/dist`:
после сборки он открывается по адресу `http://127.0.0.1:20800/`.

Архитектура, регистрация хендлеров, изменение расписания и интерфейсы ядер:
[`server/README.md`](server/README.md).
Протокол между клиентами и сервером: [`server/PROTOCOL.md`](server/PROTOCOL.md).

## Веб-интерфейс

Одностраничный клиент на Svelte 5 и TypeScript находится в папке `web`.
Нужен Node.js 20.19+ или 22.12+.

```sh
cd web
npm ci
npm run build      # собрать в web/dist, сервер раздаёт его на http://127.0.0.1:20800/
npm run dev        # dev-сервер Vite на http://localhost:5173, /ws проксируется на сервер
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
на модель сервера, `src/components` — UI-примитивы (`ui`), каркас страницы (`layout`)
и блоки интерфейса (`blocks`). Цвета, отступы и шрифты заданы переменными в
`src/styles/tokens.css`.
