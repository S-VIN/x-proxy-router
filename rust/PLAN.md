# Переписывание на Rust: архитектура и план

> Актуальная схема кода — в [FRAMEWORK.md](FRAMEWORK.md): модели с `derive(Model)`, хендлеры с `#[handler]`, без ручного протокола и сторов. Этот документ описывает цели, сборки и фазы; разделы о крейтах и DTO заменяются схемой фреймворка.

Концепция приложения не меняется: сервер управляет ядром Mihomo, хранит настройки в
SQLite, держит у клиентов копии коллекций моделей и выполняет их запросы
(`server/PROTOCOL.md`, `server/README.md`). Старые папки `server/`, `web/`, `electron/`
остаются как есть, новый код живёт в `rust/` (workspace Cargo). Сам документ —
опорный: по нему пишется код, он же потом становится `rust/README.md`.

## Что должно получиться

Две сборки из одного кода:

| Сборка | Бинарник | Из чего состоит |
| --- | --- | --- |
| Клиент-серверная | `xpr-server` | ядро приложения + WebSocket/HTTP-транспорт + вшитый веб-клиент (wasm). Docker, headless. |
| | `xpr-web` (wasm) | тот же GUI на egui, собранный в браузер; ходит на `/ws` по `PROTOCOL.md`. |
| Портативная | `xpr-desktop` | ядро приложения + тот же GUI (eframe native) + трей, автозапуск, один экземпляр. Один процесс, без сокета и без JSON между GUI и хендлерами. |

Главное требование: `xpr-desktop` — не «сервер и клиент в одном файле». Хендлеры одни и
те же, и у них один вход — `dispatch(ctx, Request)`. В клиент-серверной сборке его
вызывает транспорт для каждого протокольного сообщения, в портативной — слой GUI по
нажатию кнопки. Изменения моделей уходят клиентам одинаково: через реестр сессий, где
сессия — это либо WebSocket-соединение, либо сам GUI в том же процессе.

## Устройство

### Ключевая идея: два места стыка

```
                 ┌──────────────── xpr-app (одно и то же в обеих сборках) ───────────────┐
                 │  Context { store, core, scheduler, tasks, sync, sessions, locks }      │
                 │                                                                        │
   Request ────► │  dispatch(ctx, Request) ──► handlers::* ──► store / core               │
                 │                                   │                                    │
                 │                                   └─► sync.notify(model)               │
                 │                                         │ diff DTO, без секретов       │
                 │                                         ▼                              │
                 │                              sessions.broadcast(ServerMessage)         │
                 └──────────────────────────────────────┬───────────────────────────────-┘
                                                        │  trait SessionSink
                 ┌───────────────────────┐              │              ┌────────────────────────┐
                 │ xpr-transport-ws      │◄─────────────┴─────────────►│ LocalBackend (desktop) │
                 │ JSON ⇄ WebSocket      │                             │ mpsc ⇄ поток egui      │
                 └───────────┬───────────┘                             └───────────┬────────────┘
                             │ ws://…/ws                                           │ в процессе
                 ┌───────────▼───────────┐                             ┌───────────▼────────────┐
                 │ RemoteBackend (ewebsock)│                            │                        │
                 │ wasm и native         │                             │                        │
                 └───────────┬───────────┘                             │                        │
                             │        trait Backend (один для обоих)   │                        │
                 ┌───────────▼─────────────────────────────────────────▼────────────────────────┐
                 │ xpr-client: stores (коллекции моделей), link state, валидация, запросы        │
                 │ xpr-ui:     egui-блоки Connection / Inbounds / Servers / Subscriptions / …    │
                 └───────────────────────────────────────────────────────────────────────────────┘
```

1. **`dispatch` и типизированный `Request`.** Запрос протокола — enum в крейте
   `xpr-protocol`: `Request::AddSubscriptionLink(AddSubscriptionLink { url })`,
   `Request::ConnectOutboundServer { id }` и т. д. Serde превращает его в формат
   `PROTOCOL.md` (`type` + `model` + `payload`) и обратно. `dispatch` — один `match`,
   который вызывает хендлер с уже разобранными полями. Таблица регистрации
   `websocket.register("add", "subscription_link", …)` из Python становится этим
   `match`: компилятор не даст забыть пару или зарегистрировать её дважды.
2. **`SessionSink` и реестр сессий.** То, что в Python называлось `WebSocketServer` без
   сети (очереди соединений, `send`, `broadcast`, слушатели подключения), становится
   `Sessions`: `connect(sink) -> SessionId`, `disconnect`, `send`, `broadcast`.
   `SessionSink` — трейт с одним методом `send(&self, ServerMessage)`. Транспорт
   реализует его записью JSON в очередь сокета, `LocalBackend` — записью в `mpsc` и
   `egui::Context::request_repaint()`. `ModelSync` и хендлеры не знают, кто на другом
   конце. Снимки при подключении, порядок «изменения раньше ответа» и прочие гарантии
   протокола живут в `Sessions`/`ModelSync` и поэтому одинаковы в обеих сборках.

JSON существует только в `xpr-transport-ws` и `RemoteBackend`. В портативной сборке
GUI получает типизированные `ServerMessage` и отдаёт типизированные `Request`.

### Крейты

```
rust/
├── Cargo.toml                 workspace; версия, имя, id приложения — из ../build.json (build.rs)
├── crates/
│   ├── xpr-protocol           wire-типы: Request, ServerMessage, DTO моделей, ErrorCode. serde, wasm-safe
│   ├── xpr-domain             доменные модели с секретами, валидация, pattern, нумерация правил
│   ├── xpr-app                всё, что в server/: store, cores, handlers, tasks, scheduler, sync, sessions, dispatch
│   ├── xpr-transport-ws       axum + tokio-tungstenite: /ws, статика, проверка Origin
│   ├── xpr-client             trait Backend, stores, link state, валидация форм, RemoteBackend (feature `remote`)
│   └── xpr-ui                 egui: блоки, виджеты, токены темы, раскладка колонок
└── bin/
    ├── xpr-server             headless: xpr-app + xpr-transport-ws + вшитый dist xpr-web
    ├── xpr-web                wasm: xpr-ui + xpr-client/remote, собирается trunk
    └── xpr-desktop            xpr-app + xpr-ui + LocalBackend + eframe native + трей
```

Зависимости строго в одну сторону: `protocol ← domain ← app ← transport-ws`,
`protocol ← client ← ui`. `xpr-ui` и `xpr-client` не зависят от `xpr-app`, поэтому
собираются в wasm. `LocalBackend` живёт в `bin/xpr-desktop` (или в `xpr-client` за
feature `local`, которая тянет `xpr-app`) — это единственное место, где GUI и ядро
приложения встречаются.

### xpr-protocol

- DTO моделей ровно как в `PROTOCOL.md`: `OutboundServer`, `InboundServer`,
  `RoutingRule`, `RegFilter`, `OutboundTest`, `SubscriptionLink` (с `url_short`),
  `ServerSettings`, `Task`. Это копия `web/src/lib/api/protocol.ts`, в них нет секретов
  по построению: у `protocol::OutboundServer` просто нет поля `vless_uuid`. Это надёжнее
  метки `SECRET` в Python.
- Перечисления с «открытым» вариантом (`Open<T>` из TS): `#[serde(other)] Unknown(String)`
  или собственная `Open<T>`, чтобы старый клиент показывал новые значения как есть.
- `Request` (enum по парам `type`/`model`) с payload-структурами
  `#[serde(deny_unknown_fields)]` — это замена `expect_fields`/`field_value`.
  Ошибки разбора переводятся в `bad_request` с `details.field` через
  `serde_path_to_error`. Разбор в два шага: сначала конверт `{type, model, request_id,
  payload: RawValue}` (ошибка — `bad_request`), затем поиск пары (`unknown_request`),
  затем payload (`bad_request`), как сейчас.
- `ServerMessage::{Subscription(ModelUpdate), Response(Response)}`,
  `ModelUpdate` — enum по моделям, внутри `Delta<T> { refresh, payload: Vec<T>,
  deleted_ids: Vec<T::Id> }`. `ErrorCode`, `ResponseError`.
- Проверка совместимости: snapshot-тесты JSON по примерам из `PROTOCOL.md`.

### xpr-domain

Один модуль на модель, как `server/models/`: `OutboundServer` (с секретами, инварианты
`<protocol>_*` через конструктор или enum `ProtocolParams { Vless{..}, Shadowsocks{..},
Hysteria{..} }` — плоское хранение в SQLite остаётся, в коде лучше enum), `InboundServer`
(`InboundType`, `DEFAULT_PROXY_PORT`), `RoutingRule` (`placed`, `without`, `network()`),
`RegFilter`, `OutboundTest` (`OutboundTestRule::accepts`), `ServerSettings`, `TaskState`,
`CoreStatus`, `pattern::pattern_matches`, `platform`. Ошибки полей —
`FieldError { message, field }`, они становятся `validation_error` с `details.field`.
`impl From<&domain::X> for protocol::X` — единственная дорога к клиенту.

### xpr-app

Модули повторяют `server/`, чтобы `server/README.md` оставался картой и для Rust:

| Модуль | Что переносится | Чем |
| --- | --- | --- |
| `context.rs` | `ApplicationContext` | `Arc<Context>`; поля с внутренней изменяемостью, хендлеры берут `&Context` |
| `store/` | `settings_store.py`, та же схема `settings.sqlite3` и те же миграции | `rusqlite` (bundled), `Mutex<Connection>`, без `await` под мьютексом |
| `cores/core_client.rs` | трейт `CoreClient`, проверки inbound (bind-проба, SOCKS5-рукопожатие) | `async_trait`, `tokio::net` |
| `cores/mihomo/` | генерация конфига (YAML), процесс, REST, `outbound_config` | `serde_yaml`, `tokio::process`, `reqwest` |
| `util/child_process.rs` | «ядро не переживает сервер» | Linux `prctl(PR_SET_PDEATHSIG)`, Windows Job Object (`windows` crate), macOS — наблюдение за родителем |
| `sessions.rs` | `WebSocketServer` без сети | `Sessions`, `SessionSink`, очередь на сессию в порядке постановки |
| `sync.rs` | `ModelChannel`, `ModelSync` | diff по `PartialEq` DTO вместо сравнения JSON |
| `tasks.rs` | `TaskRegistry`, `@long_task` | `tokio::spawn` + `CancellationToken` (`tokio-util`); `long_task!`-обёртка или метод `tasks.run(name, cancels, skip_while, fut)` |
| `scheduler.rs` | обёртка над APScheduler | свой `Scheduler`: `Interval`, `Cron` (`croner`), `Once`; `add_job`, `reschedule_job`, `remove_job`, ожидание активных на `stop` |
| `handlers/` | по файлу на файл | `async fn add_reg_filter(ctx: &Context, req: AddRegFilter) -> Result<Added, RequestError>` |
| `dispatch.rs` | `WebSocketServer.register/dispatch` | `match` по `Request`; один запрос — одна задача `tokio::spawn`, как сейчас |
| `subscription_loader.rs`, `outbound_probe.rs` | загрузка подписок, TCP-пинг, скорость и HTTP-тесты через тестовый SOCKS5 | `reqwest` (features `socks`, `rustls`), `url`, `base64` |
| `application.rs` | `application()`: порядок старта и остановки | `Application::start(config) -> Arc<Context>`, `stop()` в том же порядке: планировщик → задачи → ядро → БД |

Что меняется по существу при переносе:

- Отмена задач в tokio не бросает исключение в `await`, как `CancelledError`. Долгие
  задачи получают `CancellationToken` и проверяют его в `select!`; `abort()` не
  используется, чтобы `finally`-логика (снятие статуса `running`, освобождение тестового
  inbound) выполнялась. `TaskCancelled` остаётся отдельной ошибкой → код `cancelled`.
- Хендлер получает типизированный payload вместо `dict`; текст `ValueError` модели
  больше не уходит клиенту «как есть» — уходит `FieldError`.
- `AutoConnectState` под `tokio::Mutex`, `core_lock` и `outbound_test_lock` —
  `tokio::Mutex<()>`; порядок взятия тот же, что в Python (`outbound_test_lock`, затем
  `core_lock`), фиксируется в комментарии и тесте.

### xpr-transport-ws

`axum` на tokio: `/ws` (upgrade через `tokio-tungstenite`), остальные пути — статика
(`rust-embed` с `dist/` wasm-клиента; `index.html` с `no-cache`, `assets/` с хешем —
навсегда). Проверка `Origin` как в `origin_allowed`. Пинг раз в 30 с, лимит кадра 1 МиБ,
бинарные кадры → 1003, закрытие при остановке → 1001, без compression. На соединение:
`SessionSink`, который пишет в `mpsc` писателя сокета; входящие кадры → `Request` →
`dispatch`. Этот крейт — единственный, кто знает про JSON на стороне сервера.

### xpr-client

Аналог `web/src/lib`, без egui, тестируется без UI:

```rust
pub trait Backend {
    fn status(&self) -> ConnectionStatus;             // connecting | online | offline
    fn retry_at(&self) -> Option<Instant>;
    fn reconnect_now(&self);
    fn send(&self, request: Request) -> RequestId;    // ответ придёт как ClientMessage::Response
    fn try_recv(&self) -> Option<ServerMessage>;      // GUI вычитывает каждый кадр
}
```

Интерфейс без async намеренно: egui — immediate mode, GUI один раз за кадр вычитывает
сообщения, применяет к stores и перерисовывается. Запросы ждут ответ по `RequestId`,
pending-состояние лежит в stores (как `tasks`/pending в Svelte). Stores: `Collection<T>`
(применение `Delta`), по store на модель, `LinkStatus` (`linkState`, `linkDescription` —
их же использует трей), `validation`, `ordering`, `routing`, `format`, `clock`.

`RemoteBackend` (feature `remote`): `ewebsock` — один код для wasm и native, переподключение
с паузами `500…10000 мс`, `synced` после снимков всех моделей, как в `connection.svelte.ts`.

`LocalBackend` (desktop): держит `Arc<Context>` и `tokio::runtime::Handle`. `send` →
`handle.spawn(dispatch(ctx, request))`, результат → в ту же очередь, что и `ModelUpdate`.
При создании регистрируется в `Sessions` как сессия и получает снимки. `status` всегда
`online`; состояние ядра и ошибок приходит теми же моделями, что и в браузере.

### xpr-ui

Структура повторяет `web/src/components`: `widgets/` (Button, Tag, Badge, StatusDot,
StatusChip, Meter, Stat, TextField, Select, Switch, Notice, Hint, Spinner, EmptyState),
`layout/` (Dashboard с тремя/двумя/одной колонкой по ширине, ConnectionBanner, Block),
`blocks/` (Connection, Inbounds, Servers с ServerRow/ServerDetails/TestResults,
Subscriptions, Filters, Routing, Tests и их формы), `theme.rs` (токены из `tokens.css`),
`logo.rs` (логотип в цвете состояния; он же — иконка трея и favicon).
`App::update()` каждый кадр: `drain(backend)` → stores → отрисовка; `request_repaint_after`
для часов и таймеров. Тесты экранов — `egui_kittest` (снимки).

Чем egui в браузере отличается от Svelte и с чем придётся смириться: интерфейс рисуется
на canvas — нет выделения текста браузером, системной проверки орфографии и доступности
DOM; wasm весит единицы мегабайт. Взамен — один код для всех платформ.

### bin/xpr-desktop

- Главный поток — `eframe` (winit требует этого на macOS). Tokio-рантайм — в отдельном
  потоке, он запускает `Application::start` до появления окна (как Electron ждёт порт).
- `tray-icon` + `muda`: меню Open / Launch at login / Quit, иконка по `LinkState`
  (следит за своей сессией в `Sessions`, как `linkWatcher.ts`). Закрытие окна — скрыть,
  если трей есть (на Linux — проверка `org.kde.StatusNotifierWatcher` через `zbus`).
- `auto-launch` для автозапуска с `--hidden`; `single-instance` — повторный запуск
  показывает окно; `tracing-appender` — `logs/server.log` с ротацией; папка данных и
  `window.json` — как у Electron (`directories`).
- Mihomo вшит в бинарник `include_bytes!` под `cfg(target_os, target_arch)` и
  распаковывается в папку данных при первом запуске или смене версии (по SHA-256).
  Портативная версия — действительно один файл.
- Остановка: окно и трей исчезают сразу, `Application::stop()` — по порядку, затем выход.
- Опция «открыть доступ из браузера/сети»: тот же процесс поднимает
  `xpr-transport-ws` на том же `Context`. Это ничего не стоит архитектурно и доказывает,
  что сборка одна: сессия GUI и сессии сокета равноправны.

### bin/xpr-server и bin/xpr-web

`xpr-server`: `XPR_UI_HOST`, `XPR_UI_PORT`, `XPR_DATA_DIR`, `XPR_STOP_ON_STDIN_CLOSE`
с теми же проверками и текстами; SIGINT/SIGTERM/SIGHUP; Mihomo — из `resources/mihomo`
рядом (Docker) или вшитый (feature `embed-core`). `xpr-web`: `trunk build --release`,
`dist/` вшивается в `xpr-server` через `rust-embed`; адрес сокета — `/ws` своего origin,
переопределяется при сборке переменной (аналог `VITE_WS_URL`).

### Совместимость, которая делает переход проверяемым

- `settings.sqlite3`: та же схема и версии миграций → Rust-сервер открывает базу
  Python-сервера.
- `PROTOCOL.md` — контракт без изменений → существующий Svelte-клиент (`web/dist`) и
  Electron работают с Rust-сервером. Это приёмочный тест фазы 4: подменить
  `python -m server.main` на `xpr-server` и прогнать приложение.
- Python-тесты (`server/tests`, 7,5 тыс. строк) — спецификация поведения; переносятся
  вместе с модулями, в первую очередь `test_requests`, `test_auto_connect`,
  `test_model_sync`, `test_tasks`, `test_routing_rule`, `test_inbound_server`,
  `test_outbound_check`, `test_mihomo_outbound_config`. Ядро в тестах — `FakeCore`,
  как сейчас.

### Библиотеки

Версии — последние стабильные на момент реализации, фиксируются в `Cargo.lock`.

| Область | Крейты |
| --- | --- |
| async, процессы, отмена | `tokio` (full), `tokio-util` (CancellationToken), `futures` |
| сериализация | `serde`, `serde_json`, `serde_yaml`, `serde_path_to_error` |
| хранилище | `rusqlite` (bundled) |
| сеть сервера | `axum`, `tokio-tungstenite`, `rust-embed`, `reqwest` (rustls, socks, json) |
| ядро Mihomo, ОС | `windows` (Job Objects), `libc` (prctl), `sha2` |
| планировщик | `croner` (cron), `tokio::time` — собственный `Scheduler` |
| модели | `uuid`, `url`, `regex`, `ipnet`, `time` или `chrono` (ISO 8601 UTC), `thiserror` |
| логи | `tracing`, `tracing-subscriber`, `tracing-appender` |
| GUI | `eframe`/`egui`, `egui_extras`, `ewebsock`, `egui_kittest` (тесты) |
| desktop | `tray-icon`, `muda`, `auto-launch`, `single-instance`, `directories`, `zbus` (Linux) |
| wasm | `wasm-bindgen`, `web-sys`, `trunk` (инструмент) |

## План

Каждая фаза заканчивается чем-то, что собирается, проходит тесты и показывается. Порядок
выбран так, чтобы сервер стал заменой Python-серверу раньше, чем появится GUI: его
можно проверять старым веб-клиентом.

### Фаза 0. Каркас

- `rust/Cargo.toml` workspace, крейты-заглушки, `build.rs` читает `../build.json`
  (name, productName, version, repository → app id) — один источник переменных сборки.
- CI: `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`, `cargo build
  --target wasm32-unknown-unknown -p xpr-web` (через trunk). `rust-toolchain.toml`.
- `rust/README.md` с командами разработки; корневой `README.md` получает раздел «Rust».

### Фаза 1. Протокол и домен

- `xpr-protocol`: DTO, `Request`, `ServerMessage`, `ErrorCode`; snapshot-тесты по
  `PROTOCOL.md`.
- `xpr-domain`: модели, валидация, `pattern`, `RoutingRule::{placed, without}`,
  `From<&domain> for protocol`. Переносятся тесты моделей из `test_routing_rule`,
  `test_inbound_server` (часть про модель), `test_settings_store` (часть про инварианты).

### Фаза 2. Хранилище, ядро, загрузчики

- `store/`: схема и миграции 1:1, вычисление `filtered` по `RegFilter` при чтении,
  `update_servers` с сохранением id совпавших профилей, `set_connected`, `update_health`.
  Тесты `test_settings_store`, `test_subscription_stores` — на базе Python-версии
  (можно открыть базу, созданную Python-тестами, как fixture).
- `cores/`: `CoreClient`, `mihomo::{outbound_config, inbound_config, routing_rule_config,
  domain_regex}` (чистые функции, тесты `test_mihomo_outbound_config`), `process_manager`
  (временный конфиг, свободный порт, secret, наблюдение за процессом), `rest_client`,
  `MihomoClient` (`service_start`, `inbound_set`, `routing_set`, `outbound_register`,
  `outbound_connect`, `test_connect`, …). Тест `test_mihomo` с настоящим бинарником из
  `resources/mihomo`.
- `util/child_process` под три ОС; `subscription_loader` (URI и JSON-форматы, тесты
  `test_subscription_loader`); `outbound_probe` (`test_outbound_check`, частично).

### Фаза 3. Рантайм приложения

- `Context`, `Sessions` + `SessionSink`, `ModelSync` (тесты `test_model_sync` и
  `test_transport` без сети — они как раз написаны без сокетов), `TaskRegistry`
  (`test_tasks`), `Scheduler`.
- Все `handlers/` и `dispatch`; `application.rs` с порядком старта/остановки.
  Тесты `test_requests`, `test_application`, `test_auto_connect`, `test_inbound_server`,
  `test_routing_rule`, `test_outbound_check` с `FakeCore`.
- Критерий: сценарии из «Типовые сценарии» `PROTOCOL.md` проходят через `dispatch`
  без транспорта.

### Фаза 4. Сервер как замена Python-серверу

- `xpr-transport-ws`, `bin/xpr-server`: переменные окружения, сигналы, остановка по
  закрытию stdin (`test_stdin_stop`), статика (`test_static_files`), проверка Origin
  (`test_connection`).
- Приёмка: `web/dist` (Svelte) против `xpr-server`; Electron с `backend.ts`,
  запускающим `xpr-server` вместо Python. Docker-образ `docker/Dockerfile.rust`
  (многоступенчатый: cargo → scratch/distroless, Mihomo из `resources/`).
- С этого момента Rust-сервер можно выпускать в Docker, не дожидаясь GUI.

### Фаза 5. Клиентская логика

- `xpr-client`: `Backend`, `Collection`, stores, `link_state`, `validation`, `ordering`,
  `routing`, `format`; `RemoteBackend` на `ewebsock`. Перенос `stores.test.ts`,
  `connection.test.ts`, `logic.test.ts`, `logo.test.ts`.
- Интеграционный тест: `RemoteBackend` против `xpr-server` в процессе теста.

### Фаза 6. GUI на egui и веб-сборка

- `xpr-ui`: токены темы, виджеты, блоки в том порядке, в каком они нужны для работы:
  Connection → Servers → Subscriptions → Inbounds → Filters → Routing → Tests; раскладка
  1/2/3 колонки по ширине с сохранением введённого текста (блоки не пересоздаются —
  в egui это естественно: состояние форм живёт в `App`).
- `bin/xpr-web` через trunk; `dist/` вшивается в `xpr-server`. Приёмка: сценарии
  `PROTOCOL.md` руками в браузере против `xpr-server`; `egui_kittest`-снимки блоков.

### Фаза 7. Портативная сборка

- `LocalBackend`; `bin/xpr-desktop`: рантайм в потоке, окно eframe, трей, автозапуск,
  один экземпляр, лог, папка данных, `--hidden`, диалог при падении ядра/старта,
  остановка по порядку, вшитый Mihomo.
- Опция WS-транспорта в desktop (выключена по умолчанию).
- Smoke-тест как в `electron/src/main.ts`: старт, снимки моделей дошли до GUI, иконки
  трея загрузились, остановка.

### Фаза 8. Пакеты и CI

- Windows: инсталлер (NSIS, переиспользовать `installer.nsh`) и портативный exe;
  Linux: AppImage (`linuxdeploy`/`appimagetool`), Flatpak-манифест, PKGBUILD;
  macOS: `.app` + DMG, ad-hoc подпись по умолчанию, как сейчас.
- Workflow «Desktop application (Rust)» по матрице из `build.json`
  (`scripts/build-config.mjs github` остаётся источником матрицы); «Docker image (Rust)».

### Фаза 9. Переключение

- README: Rust-сборки — основные, `server/`, `web/`, `electron/` — отмечены как прежняя
  реализация, остаются в репозитории. `PROTOCOL.md` переезжает в корень `docs/` или
  остаётся в `server/` с пометкой, что контракт общий.

## Риски и открытые вопросы

- **egui в браузере.** Canvas вместо DOM: хуже доступность и работа с текстом. Принято
  осознанно ради одного кода GUI.
- **Отмена задач.** Кооперативная отмена через `CancellationToken` требует дисциплины
  в долгих задачах; проверяется тестами `test_tasks`/`test_outbound_check` (прерывание
  проверки обновлением подписок).
- **Трей на Linux.** `tray-icon` опирается на libappindicator/StatusNotifier — те же
  ограничения GNOME, что и у Electron.
- **SOCKS5 для проверок.** `reqwest` с `socks` ходит через тестовый inbound по TCP;
  UDP-проверок нет и не было.
- **Размер wasm и время сборки.** Отдельный профиль `release` с `opt-level = "s"`,
  `wasm-opt`; CI кэширует `target/`.
- **Windows Job Objects и macOS.** На macOS нет `PR_SET_PDEATHSIG`: ядро следит за
  родителем по pipe/`kqueue`, как и сейчас в `child_process.py`.
- **Структура `OutboundServer`.** Плоские `<protocol>_*`-поля в домене или enum параметров:
  предлагается enum в коде и плоское хранение в БД/DTO; решается в фазе 1.
