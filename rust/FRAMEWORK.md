# Фреймворк: пишем только бизнес-логику

Цель: вы объявляете модели, пишете хендлеры, слой Mihomo и экраны egui. Протокол,
хранение в SQLite, доставка данных клиентам, расписание, долгие задачи, транспорт и
обвязка окна/трея — фреймворк (`xpr-kit`). Все функции текущего приложения сохраняются;
места, где схема что-то отрезала бы, собраны в конце в разделе «Предупреждения».

## Четыре принципа

1. **Модель объявляется один раз.** `#[derive(Model)]` на структуре даёт таблицу в
   SQLite, передачу клиентам и слот в состоянии клиента. Структура одна и та же на
   сервере, в GUI и в базе.
2. **Хендлер — это и функция, и запрос.** `#[handler]` на `async fn` делает из неё
   вызов, который GUI отправляет по сети или выполняет в процессе, планировщик запускает
   по расписанию, а другой хендлер вызывает как обычную функцию. Отдельного протокола нет:
   он выводится из сигнатур.
3. **Запись в базу — это и рассылка.** `ctx.db.put(x)` сохраняет объект и отдаёт его всем
   сессиям. Никаких `notify`, сторов и подписок: GUI каждый кадр читает состояние.
4. **Сессия — это GUI или сокет, фреймворку всё равно.** В десктопе GUI живёт в том же
   процессе и зовёт хендлеры напрямую; в клиент-серверной сборке между ними сокет.
   Код хендлеров и экранов один.

```
┌────────────────────────── ваш код ───────────────────────────┐
│ models/        handlers/        core/mihomo      ui/          │
│ struct + derive  async fn + attr  trait Core impl  egui-блоки │
└──────┬──────────────┬────────────────┬───────────────┬────────┘
       │ Model        │ handler, Ctx   │ App           │ Client
┌──────▼──────────────▼────────────────▼───────────────▼────────┐
│                           xpr-kit                              │
│  Db (SQLite + кэш)   Sessions   Jobs (расписание)   Tasks      │
│  Dispatch  Transport (ws + статика)  Client: Local | Remote     │
│  Runners: Server (env, сигналы, stdin)  Desktop (трей, автозапуск)  Web (wasm)│
└────────────────────────────────────────────────────────────────┘
```

## Модели

```rust
use xpr_kit::prelude::*;

#[derive(Model, Clone, PartialEq, Serialize, Deserialize)]
#[model(name = "subscription_link")]
pub struct SubscriptionLink {
    #[model(id)]
    pub id: Id,
    #[model(secret)]          // хранится, но клиентам не уходит
    pub url: String,
    pub url_short: String,    // считается при создании, как сейчас
}

impl SubscriptionLink {
    pub fn new(url: &str) -> Result<Self, Error> {
        let parts = Url::parse(url).map_err(|_| Error::field("url", "Subscription URL must be HTTP(S)"))?;
        ...
        Ok(Self { id: Id::new(), url: url.into(), url_short })
    }
}

#[derive(Model, Clone, PartialEq, Serialize, Deserialize, Default)]
#[model(name = "server_settings", single)]      // одна запись, на проводе id: 0
pub struct ServerSettings {
    pub subscription_refresh_interval: u64,
    pub last_subscription_refresh: Option<DateTime<Utc>>,
    pub auto_connect: bool,
}

#[derive(Model, Clone, PartialEq, Serialize, Deserialize)]
#[model(name = "task", memory)]                 // не хранится, только рассылается
pub struct TaskState { #[model(id)] pub id: String, pub status: TaskStatus }
```

Что делает `derive(Model)`:

- регистрирует модель в общем реестре (`linkme`), откуда фреймворк узнаёт порядок
  снимков при подключении, имена таблиц и типы для состояния клиента;
- создаёт таблицу `subscription_link (id TEXT PRIMARY KEY, data TEXT NOT NULL)` при
  первом запуске; объект лежит в `data` как JSON. Новое поле — `#[serde(default)]`, и
  миграция не нужна;
- генерирует `for_client()`: та же структура без `#[model(secret)]`-полей;
- `single` — без поля id, читается `ctx.db.single::<T>()`, при отсутствии берётся
  `Default`; `memory` — таблица не создаётся.

Доступ из хендлеров:

```rust
ctx.db.all::<OutboundServer>()                 // Vec<T>, из кэша в памяти
ctx.db.get::<OutboundServer>(&id)              // Option<T>
ctx.db.put(server)                             // вставка или замена; равный объект — без рассылки
ctx.db.remove::<OutboundServer>(&id)           // bool
ctx.db.update::<ServerSettings>(|s| s.auto_connect = false)
ctx.db.replace::<OutboundServer>(servers)      // вся коллекция; удалённые уйдут в deleted_ids
```

Коллекции маленькие (сотни объектов), поэтому вся база живёт ещё и в памяти; SQLite —
только запись. Хендлер — единица согласованности: запись под мьютексом, без `await`.

## Хендлеры

```rust
use crate::app::Ctx;   // type Ctx = xpr_kit::Ctx<App>; App — ваше: ядро, локи, состояние

#[handler]
pub async fn add_reg_filter(ctx: &Ctx, reg: String) -> Result<Added, Error> {
    let filter = RegFilter::new(&reg)?;                                   // validation_error, field=reg
    if ctx.db.all::<RegFilter>().iter().any(|f| f.reg == filter.reg) {
        return Err(Error::conflict("reg", "Filter already exists"));
    }
    ctx.db.put(filter.clone());                     // SQLite + все клиенты
    refilter_servers(ctx).await?;                   // пересчёт filtered, отключение подключённого
    Ok(Added { id: filter.id })
}

#[handler]
pub async fn connect_outbound_server(ctx: &Ctx, id: Id) -> Result<(), Error> {
    let _core = ctx.app.core_lock.lock().await;
    let server = ctx.db.get::<OutboundServer>(&id).ok_or(Error::not_found("id"))?;
    if server.filtered.is_some() { return Err(Error::conflict("id", "Filtered servers cannot be connected")); }
    ctx.app.core.outbound_connect(&id).await.map_err(Error::core)?;
    ctx.db.update::<ServerSettings>(|s| s.auto_connect = false);   // клиенты получают server_settings
    set_connected(ctx, Some(&id));                                 // затем outbound_server
    Ok(())
}
```

Из `#[handler]` генерируется структура вызова с именем функции в CamelCase и типом
результата: `AddRegFilter { reg: String }`, `impl Call for AddRegFilter { type Output = Added; }`.
Один и тот же вызов умеют:

| Кто | Как |
| --- | --- |
| GUI | `client.call(AddRegFilter { reg })` — в десктопе выполняется в процессе, в браузере уходит по сокету |
| транспорт | находит хендлер по имени в реестре, разбирает аргументы, запускает в своей задаче, отвечает |
| планировщик | `ctx.jobs.set("refresh", Trigger::every(secs), RefreshSubscriptions {})` |
| другой хендлер | `add_reg_filter(ctx, reg).await` — просто функция |
| тест | `AddRegFilter { reg }.run(&ctx).await` |

Долгие задачи и расписание — атрибуты той же функции:

```rust
#[handler(task, cancels = [test_outbound_servers])]
pub async fn refresh_subscriptions(ctx: &Ctx) -> Result<(), Error> {
    let mut servers = Vec::new();
    for link in ctx.db.all::<SubscriptionLink>() {
        servers.extend(load_subscription(&link).await.map_err(Error::subscription(link.id))?);
    }
    replace_servers(ctx, servers);                     // id совпавших профилей сохраняются
    ctx.db.update::<ServerSettings>(|s| s.last_subscription_refresh = Some(Utc::now()));
    register_outbound_servers(ctx).await?;
    auto_connect::on_servers_changed(ctx).await
}

#[handler(task, skip_while = [refresh_subscriptions], every = "1h")]
pub async fn test_outbound_servers(ctx: &Ctx) -> Result<(), Error> {
    for server in candidates(ctx) {
        ctx.cancelled().check()?;                       // Error::Cancelled, finally-логика выполняется
        let checked = test_outbound(ctx, &server).await?;
        ctx.db.put(checked);                            // каждый сервер уходит клиентам сразу
    }
    auto_connect::on_check_run_finished(ctx).await
}
```

`task` даёт ровно то, что сейчас у `@long_task`: не больше одной задачи под именем,
повторный вызов ждёт идущую и получает её результат, `cancels` останавливает и ждёт,
`skip_while` возвращает `Ok` сразу, задача не умирает с отключившимся клиентом, её
состояние видно в модели `task`, остановка приложения отменяет все. Остановка
кооперативная: `ctx.cancelled()` — `CancellationToken`, его проверяют в циклах и
`select!`-ах.

Расписание (`ctx.jobs`): `set(name, trigger, call)`, `reschedule(name, trigger)`,
`remove(name)`, `get(name)`; `Trigger::{every(Duration), cron("30 9 * * *"), at(DateTime)}`.
Один запуск задания за раз, пропущенные объединяются, ошибка пишется в лог и расписание
не снимает, при остановке активные задания дожидаются. `every = "1h"` в атрибуте — то же,
что `set` при старте.

Ошибки — один enum, в ответ клиенту уходит код, текст и `details`:

| `Error` | код |
| --- | --- |
| `field(name, msg)` (из конструкторов моделей) | `validation_error`, `details.field` |
| `not_found(field)`, `conflict(field, msg)` | `not_found`, `conflict` |
| `core(msg)`, `subscription(failed_id)` | `core_error`, `subscription_error` |
| `Cancelled` | `cancelled` |
| всё остальное (`anyhow`) | `internal_error`, текст только в лог |
| конверт не разобран / нет хендлера / лишнее или неверное поле аргументов | `bad_request`, `unknown_request`, `bad_request` с `details.field` — генерирует фреймворк |

## Как доходят данные

```
 хендлер            Db                   Sessions                       сессии
 ───────            ──                   ────────                       ──────
 db.put(x) ───────► кэш + SQLite ──┐
                    old == new? ───┤ нет ► Update{model, [x]} ──► очередь сессии 1 (ws → JSON)
                                   │                         └─► очередь сессии 2 (GUI → mpsc)
 return Ok(out) ──────────────────────────► Reply{id, out} ──► очередь той сессии, что звала
```

Гарантии те же, что в `PROTOCOL.md`: у каждой сессии своя очередь, порядок записи
сохраняется, изменения всегда раньше ответа, при подключении — снимок каждой модели в
порядке объявления, потом только изменения. Диффа «с последней отправки» нет: запись
сама знает, что изменилось, а равный объект не рассылается.

## Клиент и GUI

`Client` один для обеих сборок. В десктопе это `LocalClient` — сессия в том же процессе
(`call` → `tokio::spawn(call.run(ctx))`, обновления через `mpsc` и `request_repaint`).
В браузере и у «удалённого» десктопа — `RemoteClient` на `ewebsock`: переподключение с
паузами `500…10000 мс`, `status`, `retry_at`, `reconnect_now`, `synced` после всех
снимков.

```rust
pub struct FiltersBlock { reg: String, adding: Option<Pending<Added>>, error: Option<String> }

impl FiltersBlock {
    pub fn ui(&mut self, ui: &mut egui::Ui, client: &Client) {
        for filter in client.state().all::<RegFilter>() {
            ui.horizontal(|ui| {
                ui.label(&filter.reg);
                if ui.button("×").clicked() { client.call(DeleteRegFilter { id: filter.id.clone() }); }
            });
        }
        ui.text_edit_singleline(&mut self.reg);
        if ui.button("Add").clicked() {
            self.adding = Some(client.call(AddRegFilter { reg: self.reg.clone() }));
        }
        match self.adding.as_mut().map(Pending::poll) {
            Some(Poll::Ready(Ok(_))) => { self.reg.clear(); self.adding = None; }
            Some(Poll::Ready(Err(e))) => { self.error = Some(e.message); self.adding = None; }
            Some(Poll::Pending) => { ui.spinner(); }
            None => {}
        }
    }
}
```

Состояние клиента (`client.state()`) — те же структуры моделей: `all::<T>()`,
`get::<T>(id)`, `single::<T>()`. Производные значения («подключённый сервер», «серверов
по подписке») — обычные функции, их зовут при отрисовке; реактивных сторов нет, потому
что egui рисует каждый кадр. Для трея есть `client.version::<OutboundServer>()` —
счётчик изменений, по которому пересчитывается иконка.

Валидация форм — те же конструкторы моделей (`RegFilter::new`), что и на сервере.

## Ваше состояние и ядро

Фреймворк ничего не знает про Mihomo. `Ctx<App>` несёт ваш `App`:

```rust
pub struct App {
    pub core: Mihomo,                           // ваша реализация trait Core
    pub core_lock: tokio::Mutex<()>,
    pub outbound_test_lock: tokio::Mutex<()>,
    pub auto_connect: tokio::Mutex<AutoConnectState>,
}
pub type Ctx = xpr_kit::Ctx<App>;
```

`trait Core` — ваш, как сейчас `CoreClient`; `MihomoCore` — ваш (процесс, REST, YAML).
Из фреймворка берутся только утилиты: `xpr_kit::process::spawn_tied` (ребёнок умирает с
родителем: Job Object, `PR_SET_PDEATHSIG`, наблюдение на macOS) и `free_port`.

## Сборка приложения

```rust
// bin/xpr-server
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    xpr_kit::Server::from_env()?                  // XPR_UI_HOST, XPR_UI_PORT, XPR_DATA_DIR, XPR_STOP_ON_STDIN_CLOSE
        .app(App::new()?)
        .on_start(app::init)                      // ядро → правила → inbound → серверы → auto_connect → расписания
        .on_stop(app::shutdown)                   // задачи → ядро; базу закроет фреймворк
        .web(xpr_kit::embed_dist!("../xpr-web/dist"))
        .run().await                              // сигналы, stdin, остановка по порядку
}

// bin/xpr-desktop
fn main() -> anyhow::Result<()> {
    xpr_kit::Desktop::new(xpr_kit::build_info!("../../build.json"))
        .app(App::new()?).on_start(app::init).on_stop(app::shutdown)
        .tray(|client| logo::state(client))      // иконка из того же состояния, что и GUI
        .remote_access(RemoteAccess::Off)         // можно включить /ws для браузера, тот же процесс
        .run(|cc, client| Box::new(Ui::new(cc, client)))
}

// bin/xpr-web
fn main() { xpr_kit::Web::run(|cc, client| Box::new(Ui::new(cc, client))); }  // /ws своего origin
```

`app::init` — обычный async-код с `ctx`: это бизнес-логика порядка старта, она ваша.
Всё, что сейчас делает Electron (окно, трей, автозапуск, один экземпляр, `--hidden`,
лог с ротацией, диалог при падении с хвостом лога, smoke-test), — в `Desktop`.

```
          десктоп (один процесс)                       клиент-сервер
 ┌──────────────┐  call.run(ctx)  ┌─────────┐      ┌─────────┐  JSON   ┌───────────┐
 │ egui-блок    │────────────────►│ handler │      │ egui    │────────►│ transport │──► handler
 │ client.call()│◄── mpsc ────────│ db.put  │      │ (wasm)  │◄─ ws ───│ sessions  │◄── db.put
 └──────────────┘   Update/Reply  └─────────┘      └─────────┘         └───────────┘
```

## Протокол на проводе

Его не пишут, он следует из объявлений, и по умолчанию совпадает с `PROTOCOL.md`: имя
хендлера `add_reg_filter` даёт `type: "add"`, `model: "reg_filter"`, аргументы —
`payload`, результат — `payload` ответа, модели — сообщения `subscription`. Так старый
Svelte-клиент и Electron остаются приёмочным тестом сервера. `PROTOCOL.md` при желании
генерируется из реестра (`xpr-server --protocol-md`).

## Что фреймворк не делает

Частичных обновлений объектов (объект уходит целиком — как сейчас), транзакций между
моделями (единица — хендлер), авторизации, конфликтов нескольких пользователей,
миграций сложнее `serde(default)`.

## Размер

`xpr-kit`: два proc-макроса (`Model`, `handler`) по ~150 строк, `Db` ~200, `Sessions`
~150, `Jobs` ~200, `Tasks` ~150, диспетчер и транспорт ~400, `Client` (local + remote)
~300, `Desktop`/`Server`/`Web` ~500. Около 2 тысяч строк, пишутся один раз, покрываются
тестами без вашей логики. Ваш код: модели, хендлеры (их столько же, сколько сейчас, но
каждый короче на разбор payload и `notify`), `auto_connect`, `mihomo`, загрузчик
подписок, пробы, экраны.

## Предупреждения: где упрощение задело бы функции

1. **Секреты в протоколе.** Вы предложили передавать их клиентам. Сейчас `url` подписки,
   пароли и сырые данные провайдера клиентам не уходят, и у сервера в Docker интерфейс
   открыт в сеть. Это потеря функции. `#[model(secret)]` стоит ~20 строк в макросе —
   предлагаю оставить, выше так и написано.
2. **Схема SQLite.** Таблицы `id, data` вместо колонок на поле: старая `settings.sqlite3`
   не откроется. Теряется «настройки переживают обновление» для тех, у кого стоит
   Python-версия. Лечится импортёром при первом запуске (~100 строк: прочитать старые
   таблицы, записать объекты, переименовать файл). Решение за вами.
3. **`filtered` считается при чтении.** В Python `BY_REG_FILTER` вычисляется из фильтров
   при каждом чтении и не хранится. Здесь поле хранится, и `refilter_servers` обязан
   вызываться в `add/delete reg_filter` и после замены серверов. Поведение то же,
   но это ваша ответственность, а не инвариант хранилища.
4. **Открытые перечисления** (`Open<T>` в TS: клиент показывает незнакомое значение как
   есть). Клиент теперь всегда той же версии, что сервер, но закэшированная старая
   страница с новым значением упадёт на разборе. Сохраняется одной строкой
   `#[serde(other)] Unknown` на каждый enum — оставить.
5. **Рассылка при записи вместо диффа.** Поведение совпадает, кроме одной мелочи: в
   Python снимок для нового клиента строился из базы, даже если `notify` забыли. Здесь
   забыть нечего, рассылает сама запись. Но запись в SQLite в обход `ctx.db` (например,
   импортёром на старте) клиентам не видна — импорт делать до открытия сессий.
6. **Один `App` вместо `ApplicationContext`-полей.** Доступ к ядру — только через
   `ctx.app.core`; `context.websocket.dispatch(...)` из Python становится
   `SomeCall { .. }.run(ctx)`. Функция сохранена, вид другой.
7. **Тесты.** 1:1 перенос 7,5 тыс. строк Python-тестов не планируется: сценарии гоняются
   через `Call::run` с `FakeCore`. Функций это не отнимает, но часть граничных случаев
   из старых тестов придётся выбирать руками.

Ничего другого из `server/README.md`, `PROTOCOL.md` и `electron/README.md` эта схема не
убирает: проверка Origin, heartbeat и лимиты сокета, статика с кешированием, переменные
окружения и остановка по stdin, порядок старта и остановки, `url_short`, нумерация правил,
автоподключение, карантины и лимиты переключений, трей, автозапуск, один экземпляр,
`--hidden`, лог, smoke-test, Docker и пакеты остаются вашим или фреймворковым кодом с
тем же поведением.
