# x-proxy-router

Проект приложения для запуска и настройки ядра Mihomo: серверная часть, затем веб-интерфейс
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

Для x86-64 используются сборки `compatible`, они работают и на старых процессорах.
Имена `linux`, `win32`, `x64`, `arm64` соответствуют значениям Node.js
`process.platform` и `process.arch`. Остальные ОС и архитектуры пока не включены.

### Повторное скачивание

Нужны Python 3.9+ и доступ к GitHub. Сторонние Python-пакеты не требуются.

```sh
python3 scripts/download-mihomo.py
```

На Windows используйте `py -3` вместо `python3`. Версия и SHA-256 архивов
закреплены в скрипте; он проверяет архив перед распаковкой, перезаписывает
бинарники и выставляет Linux-бинарникам права `0755`. Для обновления версии
нужно обновить версию и SHA-256 в скрипте из официального релиза.

### Использование сервером и Electron

Сервер сам выбирает бинарник текущей платформы, запускает его с временным
конфигом и управляет им через локальный REST API.

В Electron упаковывайте нужный бинарник через `extraResources`, вне `app.asar`;
в установленном приложении стройте путь относительно `process.resourcesPath`.
Архитектуру выбирайте для целевой сборки приложения.

В Docker копируйте только бинарник для целевой архитектуры образа:
`amd64` → `linux/x64`, `arm64` → `linux/arm64`, и задайте ему `chmod 755`.

## Серверная часть

Точка входа приложения — `server/main.py`. Запуск:

```sh
uv sync --locked
uv run python -m server.main
```

На старте создаются `SettingsStore`, клиент Mihomo и планировщик APScheduler,
запускается Mihomo (тестовый SOCKS5 `127.0.0.1:20809`), он получает сохранённые
правила роутинга, в нём запускаются сохранённые inbound (по умолчанию
SOCKS5/HTTP-прокси `127.0.0.1:20808`) и регистрируются сохранённые серверы.
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

У каждого типа inbound своя кнопка в блоке Inbounds, например «Add proxy»: она
открывает настройки нового inbound этого типа. Чтобы добавить тип, нужно:

- описать его в `INBOUND_TYPES` (по нему появляется кнопка) и `InboundDraft` в
  `src/lib/inbounds.ts` с проверками и полями запроса;
- сделать компонент настроек рядом с `ProxyFields`
  (`src/components/blocks/inbounds`);
- показать этот компонент в `InboundForm`.
