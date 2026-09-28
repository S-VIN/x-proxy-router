# Серверное приложение

Запуск из корня проекта:

```sh
uv sync --locked
uv run python -m server.main
```

`main.py` создаёт приложение и ждёт завершения по Ctrl+C или SIGTERM.
Обработчики сигналов работают через стандартный `signal.signal`, включая Windows.
Сигнал завершения контейнера Linux также обрабатывается. Принудительное завершение
процесса Windows не выполняет этот порядок остановки.

При запуске открывается `SettingsStore()` (БД `settings.sqlite3` в рабочей папке),
создаётся один `MihomoClient`, запускается планировщик. Затем, до того как
приложение готово к работе, запускается ядро:
`service_start(PROXY_PORT, TEST_PORT)` — SOCKS5 на `127.0.0.1:20808` (основной маршрут)
и `127.0.0.1:20809` (тестовый); порты — константы в `main.py`. Сразу после этого
`handlers/core.py`, `register_outbound_servers(context)` регистрирует в ядре серверы из БД.
Серверы, из параметров которых ядро не может собрать конфиг
(`check_outbound_server_config` вызывает `ValueError`), пропускаются: в лог пишется
предупреждение только с id сервера, остальные регистрируются. После регистрации
тестовый маршрут заблокирован, а основной снова подключается к серверу с
`is_connected` (см. «Подключение к серверу»). Если ядро не запустилось (например, порт занят),
приложение не запускается, а исключение выходит из `application()`.

Регистрация идёт по сохранённым серверам и не ждёт обновления подписок.
После каждого успешного `refresh_subscriptions` (на старте, по запросу клиента,
после добавления ссылки) серверы регистрируются в ядре заново тем же
`register_outbound_servers`, поэтому новые серверы из подписок сразу доступны ядру.
Перерегистрация на короткое время блокирует оба маршрута, затем основной
подключается снова к запомненному серверу. Она ждёт окончания
идущей проверки сервера (`outbound_test_lock`), чтобы не прервать её на середине.
Регистрация выполняется последней: если ядро выдало ошибку, БД и клиенты уже
обновлены, а ошибка выходит из `refresh_subscriptions`. При неудачной загрузке
подписок серверы не меняются и ядро не перерегистрируется.

При старте `handlers/init.py` запускается фоновой задачей и вызывает
`refresh_subscriptions(context)` из `handlers/subscriptions.py`: она загружает все
подписки через `load_subscription`, полностью заменяет серверы через
`context.settings.outbound_server.update_servers(servers)`
и рассылает изменения клиентам через `await context.sync.notify("outbound_server")`.
После успешной загрузки она записывает текущее время UTC в
`server_settings.last_subscription_refresh`, рассылает `server_settings` и заново
регистрирует серверы в ядре;
при ошибке серверы и время остаются прежними.
`refresh_subscriptions` — долгая задача (раздел «Долгие задачи»): одновременно идёт
не больше одного обновления, а идущий `test_outbound_servers` при старте обновления
останавливается. Запуск приложения
не ждёт загрузки подписок. При ошибке загрузки прежний список остаётся в БД,
ошибка записывается в лог. Успешный пустой результат очищает список серверов.
При завершении приложения фоновая задача отменяется до закрытия БД.
Повторяющихся расписаний два, оба ставит `main.configure_handlers`:

- `refresh_subscriptions` — каждые `server_settings.subscription_refresh_interval` секунд
  (`schedule_refresh_subscriptions` в `handlers/subscriptions.py`). Первый запуск — через
  интервал после старта: при старте подписки и так обновляет `init`. Когда клиент меняет
  интервал через `change` / `server_settings`, таймер перезапускается с новым значением
  и отсчётом от момента изменения; изменение одних `outbound_tests` его не трогает.
  Обновления по запросам и после добавления ссылки расписание не сдвигают. Ошибка
  загрузки записывается в лог планировщиком, следующий запуск — по расписанию.
- `test_outbound_servers` — раз в час (см. «Проверка серверов»).

## Структура приложения

| Файл | Ответственность |
| --- | --- |
| `main.py` | Жизненный цикл приложения, планировщик APScheduler, очереди WebSocket-соединений, разбор запросов клиентов и регистрация хендлеров |
| `request_error.py` | `RequestError`, коды ошибок `ErrorCode`, проверки полей `payload` |
| `model_sync.py` | Протокол синхронизации моделей с клиентами: `ModelChannel`, `ModelSync` |
| `models/serialization.py` | `serialize()` моделей в JSON для клиентов, метка секретных полей `SECRET` |
| `models/application_context.py` | Общий контекст для хендлеров |
| `handlers/requests.py` | Хендлеры запросов `type: request`: `request_refresh_subscriptions`, `request_test_outbound_servers`, `request_connect_outbound_server` |
| `tasks.py` | Долгие задачи: декоратор `long_task`, реестр `TaskRegistry` (`context.tasks`) |
| `outbound_probe.py` | Сетевые проверки сервера: TCP-пинг, скорость и HTTP-тесты через тестовый inbound |
| `handlers/` | Обычные async-функции, которые можно вызывать независимо от расписания |

Хендлер получает `ApplicationContext`: `settings`, `core_client`, `scheduler`,
`websocket`, `sync`, реестр долгих задач `tasks` и локи `outbound_test_lock`, `core_lock`. Поле `core_client` типизировано общим интерфейсом `CoreClient`;
реализация Mihomo выбирается в `main.py`. Все хендлеры, в том числе обработчики
WebSocket-сообщений, размещаются в `handlers/`; в `main.py` они только регистрируются.

## Независимые хендлеры и расписания

Используется [APScheduler 3.x](https://apscheduler.readthedocs.io/en/3.x/userguide.html),
версия зафиксирована в `uv.lock`. Интервалы, календарные и разовые запуски задаются
его `IntervalTrigger`, `CronTrigger` и `DateTrigger`. Обёртка `Scheduler`
оставляет расчёт времени библиотеке и обеспечивает ожидание активных хендлеров
перед закрытием ресурсов приложения.

Пример хендлера в своём модуле:

```python
import logging

from server.handlers.subscriptions import refresh_subscriptions
from server.models.application_context import ApplicationContext
from server.subscription_loader import SubscriptionError

log = logging.getLogger(__name__)

async def refresh(context: ApplicationContext) -> None:
    # Один хендлер вызывает другой как обычную функцию.
    try:
        await refresh_subscriptions(context)
    except SubscriptionError:
        log.exception("Scheduled subscription refresh failed")
```

`refresh_subscriptions` уже реализован: читает ссылки из `SettingsStore`,
загружает все подписки, заменяет ими серверы в БД и рассылает изменения клиентам.
Возвращаемое значение задачи планировщик не сохраняет.

В `main.configure_handlers(context)` можно зарегистрировать его так
(импортируйте `refresh` из своего модуля):

```python
from functools import partial
from apscheduler.triggers.interval import IntervalTrigger

context.scheduler.add_job(
    partial(refresh, context),
    IntervalTrigger(minutes=30),
    id="my-job",
)
```

Тот же хендлер доступен из другого async-хендлера через `await refresh(context)`.
Регистрация не оборачивает и не изменяет исходную функцию.

Изменение времени запуска без перезапуска приложения:

```python
from datetime import UTC, datetime, timedelta
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

# Каждые 10 минут, отсчёт начинается после изменения расписания.
context.scheduler.reschedule_job("my-job", IntervalTrigger(minutes=10))

# Ежедневно в 09:30 UTC. Можно явно задать timezone="Europe/Moscow".
context.scheduler.reschedule_job(
    "my-job", CronTrigger(hour=9, minute=30, timezone=UTC)
)

# Один раз через час; после выполнения задача удаляется из планировщика.
context.scheduler.reschedule_job(
    "my-job", DateTrigger(run_date=datetime.now(UTC) + timedelta(hours=1))
)

# Удалить будущие запуски; уже выполняющийся хендлер продолжит работу.
context.scheduler.remove_job("my-job")
```

`context.scheduler.get_job("my-job")` возвращает задание или `None`. Настоящие
задания приложения — `refresh_subscriptions` и `test_outbound_servers`: не добавляйте
второе задание с тем же хендлером.

Каждый пример изменения расписания используется отдельно. `reschedule_job` меняет
будущие запуски; текущий вызов не прерывается. Все хендлеры должны быть `async def`:
они выполняются в одном потоке с SQLite. Долгую блокирующую работу выносите отдельно;
сам `SettingsStore` в другой поток передавать нельзя.

Одновременно допускается один запланированный запуск задачи с конкретным ID.
Несколько пропущенных запусков объединяются в один. Ошибка хендлера записывается
в лог и не удаляет его расписание. Прямой вызов функции не связан с этим ограничением.
Расписания пока хранятся только в памяти и заново регистрируются при запуске.
Разные хендлеры могут выполняться параллельно; изменение состояния одного ядра
нужно вызывать последовательно, как требует `CoreClient`.

## WebSocket

Полное описание протокола для разработчиков клиентов — [PROTOCOL.md](PROTOCOL.md).

Транспорт — `aiohttp`: `WebSocketServer.start(host, port)` слушает
`ws://127.0.0.1:20800/ws` (константы `WEBSOCKET_HOST`, `WEBSOCKET_PORT`, `WEBSOCKET_PATH`
в `main.py`), `application()` запускает его после ядра и регистрации серверов.
Если порт занят, приложение не запускается. Каждый сокет подключается через
`connect()`, текстовые кадры идут в `receive()`, при закрытии вызывается `disconnect()`.
Соединения из браузера принимаются только со страниц на localhost (`origin_allowed`,
`WEBSOCKET_ALLOWED_ORIGINS`), бинарные кадры закрывают соединение (1003), сообщения
больше 1 МиБ — тоже (1009), ping — раз в 30 секунд. `stop()` (его вызывает `close()`
при остановке приложения) перестаёт слушать и закрывает сокеты с кодом 1001.
На том же порту по HTTP раздаётся собранный веб-интерфейс из `WEB_CLIENT_DIR`
(`web/dist`, модуль `static_files.py`): `/` — `index.html`, остальные пути — файлы сборки,
пути вне папки и отсутствующие файлы — 404. `index.html` отдаётся с `Cache-Control: no-cache`,
файлы из `assets/` с хешем в имени кешируются навсегда. Если сборки нет, при запуске
пишется предупреждение, а WebSocket работает как обычно.
В тестах приложение слушает свободный порт и не раздаёт интерфейс: `server/tests/__init__.py`
ставит `WEBSOCKET_PORT = 0` и `WEB_CLIENT_DIR = None`, фактический порт — `websocket.port`.

Обмен сообщениями не зависит от сети, поэтому его можно проверять без сокетов. Транспорт вызывает
`websocket.connect(connection_id, send)`, где `send(frame: str)` — async-функция записи
одного текстового кадра, `websocket.receive(connection_id, frame)` для каждого входящего
текстового кадра и `await websocket.disconnect(connection_id)` при закрытии сокета.
У каждого соединения своя очередь и задача записи: `websocket.send(connection_id, message)`
и `websocket.broadcast(message)` синхронно ставят JSON в очереди, и кадры одного
соединения уходят в порядке постановки. Ошибка `send` закрывает только это соединение.
Слушатели `add_connect_listener(listener)` вызываются при каждом подключении.
При завершении приложения `websocket.close()` отменяет выполняющиеся запросы
и закрывает соединения до остановки планировщика.

### Синхронизация моделей

Сервер держит у клиентов копии коллекций моделей. Каждое сообщение:

```json
{
  "type": "subscription",
  "model": "outbound_server",
  "refresh": false,
  "payload": [{"id": "a1b2c3d4e5f6", "name": "...", "protocol": "vless"}],
  "deleted_ids": ["0f1e2d3c4b5a"]
}
```

- `model` — имя коллекции: `server_settings`, `subscription_link`, `reg_filter`,
  `outbound_server`, `task` (в этом порядке приходят снимки при подключении). `server_settings` —
  коллекция из одного объекта с `id: 0`. `task` — долгие задачи сервера
  (раздел «Долгие задачи»).
- `payload` — объекты целиком, как их возвращает `serialize()`.
- `deleted_ids` — id удалённых объектов. При удалении `payload` пустой.
- `refresh: true` приходит при подключении, по одному сообщению на каждую модель:
  клиент заменяет всю коллекцию содержимым `payload`. Так после переподключения
  исчезают объекты, удалённые, пока клиент был офлайн.
- `refresh: false` — только изменения: клиент сначала удаляет `deleted_ids`,
  затем добавляет или заменяет по `id` объекты из `payload`. Один id не
  встречается в обоих полях.

После записи в хранилище хендлер явно вызывает `notify` с именем модели:

```python
context.settings.subscription_link.save(link)
await context.sync.notify("subscription_link")
```

`ModelChannel` хранит последнее отправленное состояние в виде JSON. `notify`
перечитывает коллекцию, сравнивает её с ним и рассылает всем клиентам
только новые, изменённые и удалённые объекты; если видимых изменений нет,
сообщение не отправляется. Изменения секретных полей клиентам не видны.
Неизвестная модель вызывает `KeyError`.
Снимок для нового клиента тоже строится из актуальных данных БД:
если после записи забыли вызвать `notify`, новый клиент всё равно получит
верные данные, а остальные — разницу. Сообщения ставятся в очередь без `await`
между чтением и постановкой, поэтому клиент не потеряет изменение между снимком
и следующей разницей.

Новая модель подключается одной строкой в `main.application()`:
`sync.register(ModelChannel("имя", store.get_all))`. Модель должна быть dataclass
с полем `id` типа `str` или `int`. Для единственной записи передаётся функция,
возвращающая список из одного объекта: `lambda: [settings.server_settings.get()]`.

#### Сериализация и секреты

`serialize(obj)` из `server/models/serialization.py` обходит поля dataclass:
enum превращается в значение, UUID — в строку, tuple — в список, datetime —
в строку ISO 8601 в UTC (`"2026-09-26T12:00:00Z"`; наивный datetime — ошибка). Поля с
`metadata=SECRET` пропускаются. Секретные поля также исключены из repr:

```python
password: str | None = field(default=None, repr=False, metadata=SECRET)
```

Клиентам не передаются: `SubscriptionLink.url`, `vless_uuid`, `vless_encryption`,
`shadowsocks_password`, `hysteria_auth`, а также сырые данные провайдера, в которых
могут быть учётные данные: `stream_options` (содержит `hysteriaSettings.auth`),
`extra_params` и `*_extra`. Вместо URL подписки клиент получает `url_short`.

### Запросы клиентов

Сообщения клиента устроены так же, как `subscription`: `type`, `model` и данные
в `payload`. `request_id` — непустая строка, которую придумывает клиент, чтобы
сопоставить ответ с запросом.

Есть два вида запросов:

- **Изменение модели** — `type` равен `add`, `change` или `delete`, в `model`
  имя изменяемой модели (`subscription_link`, `reg_filter`, `server_settings`).
- **Действие** — `type` всегда `request`, а само действие записано в `model`,
  например `refresh_subscriptions`. Новые действия, которые не сводятся
  к добавлению, изменению или удалению одной модели, добавляются только так,
  без новых значений `type`.

Запросы изменения моделей остаются в прежнем виде и на `type: request`
не переводятся.

```json
{"type": "add", "model": "subscription_link", "request_id": "c-17",
 "payload": {"url": "https://sub.example.com/token"}}
```

На каждый запрос приходит ровно один ответ:

```json
{"type": "response", "model": "subscription_link", "request_id": "c-17",
 "ok": true, "payload": {"id": "5f0c…"}}

{"type": "response", "model": "subscription_link", "request_id": "c-18",
 "ok": false, "payload": {},
 "error": {"code": "conflict", "message": "Subscription URL is already used",
           "details": {"field": "url"}}}
```

Ответ не содержит изменённых данных: они приходят сообщением `subscription`,
которое ставится в очередь соединения раньше ответа. К моменту `ok: true`
копия данных у клиента уже обновлена. Id новых объектов генерирует сервер.
Каждый запрос выполняется в отдельной задаче, поэтому долгий запрос не задерживает
остальные. Если клиент отключился, запрос завершается, но ответ не отправляется.
Пакетных запросов нет: один запрос — одно действие.

| type | model | payload | ответ `payload` |
| --- | --- | --- | --- |
| `add` | `subscription_link` | `{url}` | `{id}`; ответ приходит после загрузки серверов всех подписок |
| `change` | `subscription_link` | `{id, url?}` | `{}` |
| `delete` | `subscription_link` | `{id}` | `{}` |
| `add` | `reg_filter` | `{reg}` | `{id}` |
| `delete` | `reg_filter` | `{id}` | `{}` |
| `change` | `server_settings` | `{id: 0, subscription_refresh_interval?, outbound_tests?}` | `{}` |
| `request` | `refresh_subscriptions` | `{}` | `{}` после загрузки всех подписок |
| `request` | `test_outbound_servers` | `{}` | `{}` после проверки всех серверов |
| `request` | `connect_outbound_server` | `{id}` | `{}` после переключения ядра |

`request` / `refresh_subscriptions` вручную запускает `refresh_subscriptions`:
загружает все подписки, заменяет серверы и записывает `last_subscription_refresh`.
Изменения `outbound_server` (если серверы изменились) и `server_settings` приходят
до ответа. Если обновление уже идёт (при старте, после `add` или от другого клиента),
новое не запускается: ответ приходит, когда закончится идущее, с его результатом.
При ошибке загрузки — `subscription_error` с `details.failed_id`, серверы
и время обновления не меняются.

`request` / `test_outbound_servers` вручную запускает проверку серверов
(`test_outbound_servers`); отфильтрованные пропускаются, кроме `by_ping`. Статус задачи `test_outbound_servers` в модели `task` сразу
становится `running`; каждый сервер после своей проверки сразу приходит клиентам
в `outbound_server` с новыми `ping`, `speed`, `rating`, `tests`; в конце статус
`stopped`, затем ответ. Если проход уже идёт, новый не запускается и ответ приходит
по окончании идущего. Пока обновляются подписки, проверка не запускается: `conflict`.
Если обновление подписок начнётся во время прохода, он прерывается: `cancelled`.

`request` / `connect_outbound_server` направляет основной трафик ядра через сервер
`id` (`connect_outbound_server`). Клиенты получают `outbound_server` с новым
`is_connected` у нового и прежнего сервера до ответа. Сервера нет в БД — `not_found`;
ядро не смогло переключиться (например, сервер не зарегистрирован из-за
неподдерживаемых параметров) — `core_error` с `details.id`, прежнее подключение
сохраняется. Сервер отфильтрован — `conflict` с `details.id`. Отключения нет:
подключение только меняется на другой сервер.

`add` / `reg_filter` и `delete` / `reg_filter` добавляют и удаляют фильтр серверов
по имени (`handlers/reg_filter.py`). До ответа клиенты получают `reg_filter`
и `outbound_server` с серверами, у которых изменилось `filtered` (раздел
«Фильтрация серверов»). Неверное выражение — `validation_error`, такое же уже
есть — `conflict`, оба с `details.field = "reg"`. Изменения фильтра нет.

`add` / `subscription_link` сначала дожидается идущего обновления (оно прочитало
ссылки до добавления новой), а затем запускает своё, поэтому серверы новой ссылки
всегда загружаются.

В `change` передаются `id` и только изменяемые поля. Неизвестные поля отклоняются,
в том числе `url_short` и `last_subscription_refresh`: их ведёт сервер.

`outbound_tests` в `change` / `server_settings` — полный новый список
`[{url, alias, rule}, ...]`: он заменяет прежний, `[]` удаляет все проверки.
У каждого элемента обязательны все три поля, лишние отклоняются. Ошибки
указывают элемент в `details.field`: `outbound_tests[1]` (элемент не объект
или неверный URL/пустой alias), `outbound_tests[1].rule` (нет поля, неверный тип,
неизвестное правило). Повторяющийся `alias` — `validation_error`.
Результаты проверок серверов (`ping`, `speed`, `rating`, `tests`) клиенты
не меняют: их записывает сервер.

| code | когда |
| --- | --- |
| `bad_request` | не JSON-объект; `request_id`, `type` или `model` не непустая строка; `payload` не объект; нет обязательного, есть неизвестное или неверного типа поле (`details.field`) |
| `unknown_request` | нет хендлера для пары `type` + `model` |
| `validation_error` | `ValueError` модели, например URL не HTTP(S), интервал ≤ 0, неизвестное правило или повторяющийся alias проверки |
| `not_found` | объекта с таким `id` нет |
| `conflict` | `sqlite3.IntegrityError`, например одинаковый URL подписки |
| `core_error` | ядро не выполнило действие; подробности только в логе сервера |
| `cancelled` | долгую задачу остановила другая задача или остановка приложения (`TaskCancelled`) |
| `subscription_error` | подписки не загрузились, серверы остались прежними. `details.failed_id` — подписка, которая не загрузилась. Для `add` ссылка всё равно сохранена, и в `details.id` — её id |
| `internal_error` | любое другое исключение; текст пишется только в лог, клиент получает «Internal server error» |

В ответе на неразобранное сообщение `request_id` и `model` равны `null`,
если их не удалось прочитать.

#### Хендлеры

Хендлер — обычная async-функция в `handlers/`, которая сама разбирает `payload`
и возвращает `payload` ответа. После записи в хранилище она вызывает `notify`:

```python
from server.request_error import ErrorCode, RequestError, expect_fields, field_value

async def delete_subscription_link(context, payload):
    expect_fields(payload, {"id"})  # обязательные и необязательные поля
    if not context.settings.subscription_link.delete(field_value(payload, "id", str)):
        raise RequestError(ErrorCode.NOT_FOUND, "Subscription link not found", {"field": "id"})
    await context.sync.notify("subscription_link")
    return {}
```

`field_value(payload, name, str | int)` проверяет тип поля (`bool` не считается
числом). Для вложенных объектов обе функции принимают `prefix`: с
`prefix="outbound_tests[1]."` ошибка называет поле `outbound_tests[1].url`.
`RequestError(code, message, details)` отправляется клиенту как есть,
поэтому в нём не должно быть секретов. Это относится и к тексту `ValueError`:
он уходит клиенту в `validation_error`.

Регистрация — в `main.configure_handlers(context)`:

```python
from functools import partial

context.websocket.register("delete", "subscription_link", partial(delete_subscription_link, context))
```

Повторная регистрация той же пары вызывает `ValueError`. Из async-кода хендлер
можно вызвать через `await context.websocket.dispatch("delete", "subscription_link", {"id": ...})`
(для неизвестной пары — `RequestError` с `unknown_request`) или напрямую.
Для обращения к ядру обработчик использует `context.core_client`, например
`await context.core_client.service_start(proxy_port=1080, test_port=1081)`.

## Завершение

Приложение прекращает будущие запуски, ждёт текущие задания планировщика,
останавливает Mihomo и закрывает SQLite. `SettingsStore` закрывает только владелец
жизненного цикла, а не отдельные хендлеры. Хендлер должен завершать свою работу:
бесконечное ожидание внутри него задержит штатную остановку приложения.
Долгие задачи (`@long_task`) останавливаются явно, `context.tasks.cancel_all()`,
до остановки планировщика, поэтому их не приходится ждать до конца.

## Подключение к серверу

`handlers/core.py`:

- `connect_outbound_server(context, server_id)` вызывает
  `core_client.outbound_connect`, затем ставит серверу `is_connected` (у прежнего
  флаг снимается) и рассылает `outbound_server`. Возвращает сервер или `None`, если
  его нет в БД. Отфильтрованный сервер — `ServerFiltered`, ядро не вызывается.
  Если ядро не смогло переключиться, вызывает `CoreError` с текстом
  для клиента, причина пишется в лог, прежнее подключение сохраняется.
- `register_outbound_servers(context)` после регистрации серверов снова подключает
  основной маршрут к серверу с `is_connected`. Если этот сервер не зарегистрирован
  (ядро не поддерживает его параметры) или ядро не смогло к нему подключиться,
  флаг снимается и клиенты получают `outbound_server`. Так подключение
  восстанавливается при запуске приложения и после каждого обновления подписок.

Смены основного маршрута и регистрация идут по одной (`context.core_lock`), чтобы
восстановление после регистрации не перебило подключение, выбранное клиентом.

## Фильтрация серверов

`OutboundServer.filtered: FilterReason | None` — почему сервер отфильтрован:
`BY_REG_FILTER`, `BY_PING`, `BY_SUBSCRIPTION` (пока не ставится). Отфильтрованный
сервер остаётся в БД и у клиентов, но к нему нельзя подключиться, и проверки его
пропускают, кроме `BY_PING`.

- **`BY_REG_FILTER`** не хранится. `RegFilter(id, reg)` лежат в таблице
  `reg_filters` (`context.settings.reg_filter`: `get_all`, `add`, `delete`).
  `OutboundServerStore` при каждом чтении (`get_all`, `get_by_id`, `get_connected`,
  результаты `set_connected` и `update_health`) ищет `reg` в `name` через
  `re.search` и ставит `BY_REG_FILTER`, если подошёл хоть один фильтр. Поэтому
  после изменения фильтров серверы не переписываются: хендлер только вызывает
  `notify("outbound_server")`, и клиенты получают серверы с изменившимся `filtered`.
  Новые серверы из подписок фильтруются так же. `save()` сервера с
  `BY_REG_FILTER` записывает в колонку `NULL`.
- **`BY_PING`** хранится в колонке `filtered`. Его ставит `test_outbound`, если TCP-сервер
  не ответил на пинг, и снимает при удачном пинге (`update_health(..., filtered=...)`;
  `BY_REG_FILTER` туда передать нельзя — `ValueError`). Обновление подписок сохраняет
  его, как остальные результаты проверок. `BY_REG_FILTER` важнее и закрывает его,
  пока фильтр есть.
- `test_outbound_servers` пропускает серверы с `filtered`, кроме `BY_PING`: их
  проверяют снова, чтобы сервер мог вернуться. Сервер перечитывается перед
  проверкой, поэтому фильтр, добавленный во время прохода, действует на оставшиеся.
- `connect_outbound_server` для отфильтрованного сервера вызывает `ServerFiltered`.
- В ядре регистрируются все серверы, в том числе отфильтрованные, и подключённый
  сервер, попавший под фильтр, остаётся подключённым. Перерегистрация блокирует оба
  маршрута ядра, поэтому изменение фильтров ядро не трогает: фильтр соблюдает
  приложение.

Выражения пользователь пишет сам, а `re` не ограничивает время поиска: выражение
с катастрофическим перебором (например, `(a+)+$`) может надолго занять event loop
при каждом чтении серверов.

## Долгие задачи

`server/tasks.py`. Долгая задача — async-хендлер с именем, который можно найти
и остановить из другого хендлера. Объявляется декоратором, вызывается как обычно:
напрямую, из запроса или планировщиком. Первый аргумент — `ApplicationContext`.

```python
from ..tasks import long_task

@long_task("test_outbound_servers", skip_while=["refresh_subscriptions"])
async def test_outbound_servers(context: ApplicationContext) -> None: ...

@long_task("refresh_subscriptions", cancels=["test_outbound_servers"])
async def refresh_subscriptions(context: ApplicationContext) -> None: ...
```

- Под одним именем одновременно идёт не больше одной задачи. Если задача уже идёт,
  новая не запускается: вызвавший ждёт идущую и получает её результат или ошибку.
- `cancels` — задачи, которые останавливаются (с ожиданием их завершения) перед стартом.
- `skip_while` — пока идёт одна из этих задач, вызов сразу возвращает `None`, ничего не запуская.
- Задача выполняется в своей задаче asyncio: отмена вызвавшего (например, клиент
  отключился) её не останавливает. Остановить можно только через реестр.
- Остановленная задача получает `CancelledError` в ближайшем `await`, поэтому её
  `finally` выполняются. Все её вызвавшие получают `TaskCancelled`: планировщик пишет
  это в лог как INFO, запрос клиента получает ошибку `cancelled`.

Реестр — `context.tasks`:

```python
await context.tasks.cancel("test_outbound_servers")  # остановить и дождаться; нет задачи — ничего
await context.tasks.wait("refresh_subscriptions")    # дождаться, чем бы она ни закончилась
context.tasks.running("refresh_subscriptions")        # идёт ли сейчас
await context.tasks.cancel_all()                     # при остановке приложения
```

Задача не может остановить сама себя (`RuntimeError`).

### Статусы задач для клиентов

Модель `task` (`server/models/task_state.py`, `TaskState`): по объекту на каждую
задачу, объявленную через `@long_task`, даже если она сейчас не идёт.
`id` — имя задачи, `status` — `running` или `stopped` (`TaskStatus`).
Задачи отсортированы по имени.

```json
{"type": "subscription", "model": "task", "refresh": false,
 "payload": [{"id": "refresh_subscriptions", "status": "running"}], "deleted_ids": []}
```

При подключении клиент получает снимок всех задач, дальше — только задачи,
у которых сменился статус. Реестр сообщает о смене сам (`TaskRegistry(on_change=...)`,
в приложении — `sync.notify("task")`): `running` уходит при старте задачи,
`stopped` — при завершении, как бы она ни закончилась. Присоединение к уже идущей
задаче и пропуск по `skip_while` статус не меняют. Для запроса, запустившего задачу,
`stopped` приходит до ответа. Новая задача появляется у клиентов, как только её
модуль объявлен декоратором; хендлеры для этого писать не нужно.

## Управление ядрами

Реализация Mihomo с тем же `CoreClient`, REST API и отдельным тестовым SOCKS:
[документация Mihomo](cores/mihomo/README.md).

## Управление Xray

Общий `CoreClient` предоставляет командный интерфейс: запуск двух фиксированных
SOCKS-портов, полная замена списка через `outbound_register(servers)`, выбор сервера
по `id` и `outbound_delete_all()`. Имена outbounds равны `OutboundServer.id` без
префикса. Замена списка сбрасывает оба маршрута в блокировку; у Xray она не атомарна.

Python **3.11+**. Установка зависимостей: `python -m pip install -r server/requirements.txt`. Общий экземпляр менеджера:

```python
from server.cores.xray.xray_process_manager import xray
from server.cores.xray.xray_grpc_client import XrayGrpcClient

async def application():
    client = XrayGrpcClient()
    await xray.start()
    print(f"gRPC: 127.0.0.1:{xray.api_port}")
    try:
        await client.connect(xray.api_port)
        print(xray.status())
        print(await client.list_outbounds())
        # Здесь работает сервер.
    finally:
        await client.close()
        await xray.stop()
```

`xray` — объект на уровне модуля. Все его импорты получают один экземпляр;
сам класс `XrayProcessManager` допускает создание независимых объектов, например в тестах.

## Интерфейс

| Метод | Поведение |
| --- | --- |
| `await start()` | Сгенерировать конфиг и запустить Xray с локальным gRPC API |
| `await stop()` | Запросить завершение и дождаться выхода |
| `status()` | Состояние, PID, код выхода и ошибка |
| `api_port` | Выбранный свободный порт API; `None` до запуска и после остановки |
| `binary_path` | Абсолютный путь к бинарнику текущей платформы |

Для перезапуска последовательно вызовите `stop()` и `start()`. `stop()` можно вызывать повторно. `start()` при активном мониторинге
вызывает `XrayError`. Вызывающая сторона должна выполнять операции последовательно
в одном event loop: защиты от одновременных вызовов нет.

Состояния: `STOPPED`, `STARTING`, `RUNNING`, `STOPPING`, `FAILED`.
`RUNNING` означает, что процесс создан. Менеджер не создаёт gRPC-клиент и не
ожидает готовности API. Приложение отдельно вызывает `client.connect(xray.api_port)`. SOCKS5 ещё не настроен.
Конфигурацию проверяет сам Xray при запуске. При неожиданном выходе менеджер
сохраняет код и сообщение об ошибке. stdout и stderr объединены, постоянно читаются
одной задачей наблюдения и передаются в стандартный logger `server.cores.xray.xray_process_manager`.
История логов внутри менеджера не хранится.

При неожиданном завершении состояние становится `FAILED`. Повторный запуск
выполняется приложением через `start()`.

## Минимальный конфиг

Приватный метод `XrayProcessManager._generate_config()` формирует стартовую конфигурацию:

- `log`: уровень `info`, журнал подключений отключён (`access: "none"`).
- `api`: локальный адрес `127.0.0.1:<api_port>`, `HandlerService` и `RoutingService`.
- `routing`: `domainStrategy: "AsIs"`, пустой список правил.
- `outbounds`: один `blocked` (`blackhole`) для трафика без назначенного маршрута.

SOCKS5 inbound, VLESS/direct outbounds и правила приложение добавляет через gRPC.
DNS, FakeDNS, статистика и балансировщики не настроены. Управление доступно через `client`.

Перед запуском менеджер открывает временный TCP-сокет на `127.0.0.1:0`, получает
свободный порт от ОС и закрывает сокет. Номер сохраняется в публичном поле
`api_port` и записывается в конфиг. Между закрытием проверочного сокета и запуском
Xray порт может занять другой процесс; резервирование порта не выполняется.
Вывод Xray используется только для логирования, его формат не разбирается.

JSON хранится во временной папке ОС и удаляется при `stop()` или ошибке создания
процесса. При остановке или обнаружении завершения Xray `api_port` становится `None`.
Каждый явный `start()` выбирает порт заново. Изменения через gRPC не записываются
в файл: после нового запуска приложение должно восстановить обработчики и правила.

## Остановка

Используется `Process.terminate()`: SIGTERM на Linux и TerminateProcess на Windows.
Таймаута и последующего SIGKILL нет; на Linux процесс, игнорирующий SIGTERM,
может удерживать `stop()` в ожидании. Очистки при отмене асинхронных операций и
защиты при смерти Python нет. Приложение вызывает `stop()` при штатном завершении,
например в `finally` своего lifespan. При падении Python Xray может продолжить работу.

## Платформы и ресурсы

Все модели и enum находятся в `server/models`: `OperatingSystem`, `Architecture`,
`CoreState` и `CoreStatus`. Их можно импортировать напрямую из `server.models`.

`server.utils.detect_platform()` возвращает пару enum
`tuple[OperatingSystem, Architecture]`: `LINUX`/`WINDOWS` и `X64`/`ARM64`.
Строковые значения `.value` (`linux`/`win32`, `x64`/`arm64`) соответствуют папкам ресурсов.
32-битные Python и неподдерживаемые платформы отклоняются явно. Ресурсы находятся
относительно репозитория в `resources/xray/<os>/<arch>/xray[.exe]`, независимо
от текущего рабочего каталога. `XRAY_LOCATION_ASSET` указывает на папку бинарника.
Если конфиг использует GeoIP/GeoSite, соответствующие базы нужны в этой папке.

В Docker и десктопной поставке сохраняйте взаимное расположение `server` и
`resources`; копируйте комплект целевой архитектуры. Linux-бинарнику нужны права
исполнения. На Windows используйте стандартный ProactorEventLoop, поддерживающий
асинхронные subprocess. Xray запускается напрямую, без launcher и Job Object;
клиент использует `grpcio` и `protobuf`.

## Проверки

```sh
python3 -m unittest discover -s server/tests -v
```

Тесты используют настоящий бинарник текущей платформы: запуск и остановку,
проверку сгенерированного конфига, вызовы Python gRPC-клиента, SOCKS5 handshake,
добавление/удаление обработчиков и переключение маршрутов,
очистку временного файла, отсутствие бинарника и сохранение `FAILED` после падения.

## gRPC-клиент

`server/cores/xray/xray_grpc_client.py` содержит `XrayGrpcClient`. Методы:

- `add_inbound(config)`, `remove_inbound(tag)`, `list_inbounds()`;
- `add_outbound(config)`, `remove_outbound(tag)`, `list_outbounds()`;
- `replace_rules(rules)`, `append_rules(rules)`, `remove_rule(tag)`, `list_rules()`;
- `test_route(context)` — проверить, какой outbound выберут правила.

Все методы асинхронные. Добавление принимает protobuf-объекты из
`server.cores.xray.grpc_generated`, а не JSON-конфиги. `typed_message(message)` упаковывает
настройки в используемый Xray тип `TypedMessage`.

```python
from server.cores.xray.xray_grpc_client import typed_message
from server.cores.xray.grpc_generated.core.config_pb2 import OutboundHandlerConfig
from server.cores.xray.grpc_generated.proxy.freedom.config_pb2 import Config as FreedomConfig
from server.cores.xray.grpc_generated.app.router.config_pb2 import RoutingRule

# После await xray.start() и await client.connect(xray.api_port):
await client.add_outbound(OutboundHandlerConfig(
    tag="direct", proxy_settings=typed_message(FreedomConfig()),
))
await client.replace_rules([
    RoutingRule(rule_tag="selected", inbound_tag=["socks"], tag="direct"),
])
```

SOCKS inbound здесь предполагается уже добавленным. Готовые сборщики параметров
SOCKS/VLESS пока не реализованы; доступные protobuf-схемы позволяют собрать их вручную.
`replace_rules` заменяет все правила и очищает балансировщики; `domainStrategy`
остаётся из стартового конфига. `list_rules` возвращает только теги правил и outbound,
не полные условия. Переключение применяется к новым соединениям.

Каждый RPC обёртки имеет фиксированный таймаут 5 секунд.
Ошибки Xray передаются как `grpc.aio.AioRpcError`, автоматического повтора команд нет.
Для остальных вызовов доступны `client.handlers` и `client.routing` — сгенерированные
клиенты сервисов; при прямом вызове передавайте `timeout` самостоятельно.
Соединение локальное, без TLS, использование HTTP-прокси окружения отключено.

Менеджер процесса и gRPC-клиент не импортируют друг друга и не управляют друг другом.
Приложение закрывает клиент само и после нового запуска передаёт ему новый порт.
Клиент создаётся отдельно:
`client = XrayGrpcClient()`, `await client.connect(port)`, `await client.close()`.
Вызовы до подключения или после закрытия возвращают `RuntimeError`.

## Модель сервера подписки

`server/models/outbound_server.py`: `OutboundServer` и enum `OutboundProtocol`,
`OutboundTransport`, `OutboundSecurity`. Это данные одного удалённого сервера,
без загрузки подписки и преобразования в protobuf. Разбор выполняется в
`server/subscription_loader.py` (приватная функция `_parse_subscription`, вызываемая загрузчиком).

Проверенные ответы на 17.09.2026 с User-Agent `v2rayN/7.0`:

| Источник | Формат ответа | Содержимое |
| --- | --- | --- |
| sub.alvsub.cc | Base64 от списка URI, по одному на строку | 11 VLESS; TCP/gRPC + Reality |
| your-durev.com | gzip → Base64 от списка URI, по одному на строку | 35 VLESS; WS + TLS, XHTTP + Reality |
| connliberty.com | JSON-массив полных конфигов Xray | 40 конфигов; 50 VLESS, 4 Hysteria, 3 Shadowsocks outbound |

Количество записей может изменяться. Формат зависит от запроса клиента;
проверка не гарантирует одинаковый ответ для других User-Agent.
JSON также содержит freedom/blackhole и профили с несколькими серверами и
балансировщиками. Один профиль не равен одному серверу. Повторяющиеся серверы
в разных профилях здесь не дедуплицировались. Локальные DNS, inbound, routing
и балансировщики не относятся к `OutboundServer`.

### Соответствие полей

| Модель | VLESS URI | Xray JSON |
| --- | --- | --- |
| name | декодированный фрагмент после `#` | remarks профиля / tag outbound |
| address, port | host, port | settings.vnext[].address/port |
| vless_uuid (UUID) | userinfo перед `@` | settings.vnext[].users[].id |
| vless_encryption, vless_flow | encryption, flow | поля пользователя VLESS |
| transport, security | type, security | streamSettings.network/security |
| server_name, fingerprint | sni, fp | tlsSettings/realitySettings.serverName/fingerprint |
| public_key, short_id | pbk, sid | realitySettings.publicKey/shortId |
| alpn | список alpn через запятую | tlsSettings.alpn |
| host, path, grpc_mode / xhttp_mode | host, path, mode | wsSettings/xhttpSettings и другие настройки транспорта |
| service_name | serviceName | grpcSettings.serviceName |
| extra_params | неизвестные query-параметры | — |

Hysteria использует settings.address/port/version и
streamSettings.hysteriaSettings.auth (`hysteria_auth`).
Shadowsocks использует settings.servers[].address/port/password/method
(`shadowsocks_password`, `shadowsocks_method`).
`vless_extra`, `shadowsocks_extra`, `hysteria_extra` сохраняют дополнительные
настройки соответствующего протокола;
`stream_options` — дополнительные настройки streamSettings с исходной структурой,
включая xhttpSettings.extra, finalmask и sockopt.
`extra_params` сохраняет URI-параметры, например concurrency, x-durev-block,
x-durev-prio, без предположений об их назначении.

`subscription_id` — внутренний идентификатор подписки приложения.
`source_tag` — исходный тег провайдера; он может повторяться между профилями.
Уникальный тег для Xray приложение назначит отдельно. UUID, пароли и сырые
настройки провайдера помечены `SECRET`: они исключены из repr и не отправляются
клиентам, но остаются доступными полями. Модель не валидирует параметры подключения. Парсер проверяет адрес, порт,
UUID и значения enum при импорте.

Структура URI сверена с [предложением формата VLESS](https://github.com/XTLS/Xray-core/discussions/716).
Секретные URL подписок и данные доступа в репозиторий не сохранены.

### Типизация OutboundServer

`OutboundServer` — одна плоская структура для всех протоколов. `protocol`
передаётся явно, а настройки протоколов — полями с префиксом имени протокола:

- VLESS: обязательный `vless_uuid: UUID`, `vless_encryption` (по умолчанию `"none"`),
  `vless_flow: VlessFlow` (по умолчанию `VlessFlow.NONE`), `vless_extra`;
- Shadowsocks: обязательные `shadowsocks_password` и `shadowsocks_method: ShadowsocksMethod`,
  `shadowsocks_udp_over_tcp` (по умолчанию `False`), `shadowsocks_uot_version: UotVersion | None`,
  `shadowsocks_extra`;
- Hysteria: обязательный `hysteria_auth`, `hysteria_version: Literal[2]` (по умолчанию 2),
  `hysteria_extra`.

Поля работоспособности заполняет сервер по результатам своих проверок, а не подписка.
Пока сервер не проверялся, все они `None`:

- `ping: int | None` — задержка в миллисекундах;
- `speed: int | None` — скорость загрузки в байтах в секунду;
- `rating: int | None` — общая оценка для выбора сервера, больше — лучше;
- `tests: dict[str, bool] | None` — результаты `ServerSettings.outbound_tests`:
  alias проверки → прошёл ли сервер;
- `filtered: FilterReason | None` — почему сервер отфильтрован (раздел
  «Фильтрация серверов»).

`ping`, `speed` и `rating` должны быть неотрицательными целыми, значения `tests` —
`bool`, иначе `ValueError`. Поля не секретные и приходят клиентам в `outbound_server`.
Поля заполняет хендлер `test_outbound` (раздел «Проверка серверов»). После удаления или переименования проверки
её старый alias остаётся в `tests` до следующей проверки сервера.

`is_connected: bool` (по умолчанию `False`) — основной маршрут ядра идёт через этот
сервер. `True` бывает не больше чем у одного сервера, это держит и уникальный индекс
в БД. Меняет его только `connect_outbound_server`; обновление подписок сохраняет
флаг у совпавшего профиля, а если сервер пропал из подписок, флаг пропадает вместе с ним.

Все протокольные поля объявлены как `... | None = None`. При создании модель
заполняет умолчания активного протокола (`*_extra` — пустым словарём) и вызывает
`ValueError`, если не задано обязательное поле активного протокола или задано
поле другого протокола. Поэтому поля неактивных протоколов всегда `None`.
Проверка выполняется только при создании: чтобы сменить протокол через
`dataclasses.replace`, поля старого протокола нужно явно сбросить в `None`.
Режимы транспорта разделены на `GrpcMode` и `XhttpMode`.
В словарях дополнительных параметров вместо `Any` используется рекурсивный
`JsonValue`: только JSON-совместимые значения.

```python
from uuid import UUID
from server.models import (
    OutboundServer, OutboundProtocol, OutboundSecurity, VlessFlow,
)

server = OutboundServer(
    name="Example",
    address="example.com",
    port=443,
    protocol=OutboundProtocol.VLESS,
    vless_uuid=UUID("00000000-0000-0000-0000-000000000001"),
    vless_flow=VlessFlow.VISION,
    security=OutboundSecurity.REALITY,
)
```

Имена, адреса, SNI, ключи, пути, ALPN и fingerprint остаются строками:
это открытые значения, а не закрытый набор вариантов. `encryption` VLESS тоже
остаётся строкой: кроме `none`, значение может включать параметры шифрования.
Модель VLESS сейчас использует UUID из проверенных подписок; произвольные
строковые идентификаторы VLESS потребуют отдельного расширения.
Enum используют канонические значения; альтернативные обозначения провайдеров
нормализует парсер подписок. Аннотации dataclass предназначены для IDE
и статической проверки; при создании проверяется только соответствие полей протоколу.

## Хранилища настроек, подписок и серверов

`ServerSettings` (`server/models/server_settings.py`) — неизменяемые настройки
всего сервера, одна запись с `id`, всегда равным 0 (в конструктор не передаётся):

- `subscription_refresh_interval: int` — интервал обновления подписок в секундах,
  положительное число; по умолчанию 86400 (сутки);
- `last_subscription_refresh: datetime | None` — время последнего обновления подписок
  в UTC; `None`, пока обновления не было. Принимается только datetime с часовым
  поясом, он приводится к UTC;
- `outbound_tests: tuple[OutboundTest, ...]` — проверки, которые проходят
  outbound-серверы; по умолчанию пусто. `alias` не должны повторяться, иначе `ValueError`.
  Хранится кортежем, чтобы замороженная модель не менялась; клиентам уходит JSON-массив.

`OutboundTest` (`server/models/outbound_test.py`) — неизменяемое описание одной
HTTP-проверки:

- `url: str` — HTTP(S)-адрес, который запрашивается через проверяемый сервер;
  не секретный, клиенты его видят и меняют;
- `alias: str` — непустое имя проверки, ключ в `OutboundServer.tests`;
- `rule: OutboundTestRule` — какой HTTP-статус ответа считается успехом.

| `OutboundTestRule` | проверка пройдена, если статус |
| --- | --- |
| `status_204` | ровно 204 (адреса вида `generate_204`) |
| `status_2xx` | 200–299 |
| `status_below_400` | меньше 400 |
| `status_below_500` | меньше 500 |
| `status_below_503` | меньше 503 |
| `any_status` | любой: сайт ответил |

`rule.accepts(status)` возвращает, подходит ли статус под правило. Нет ответа
(таймаут, ошибка соединения) — проверка не пройдена при любом правиле.

`SubscriptionLink(url=..., id=...)` — неизменяемая модель. `id` по умолчанию
генерируется как строковый UUID, URL помечен `SECRET`: исключён из repr и не отправляется клиентам.
`url_short` — схема и хост URL без учётных данных, порта, пути и параметров,
например `https://user:token@Sub.Example.com:8443/token` → `https://sub.example.com`.
Это поле вычисляется из `url` при каждом создании модели, в том числе при чтении
из БД и в `dataclasses.replace`; передать его в конструктор нельзя, в БД оно не хранится.
Клиенты получают `id` и `url_short`.

### Настройки в SQLite

`server/settings_store.py`, класс `SettingsStore` хранит модельные структуры
в SQLite без кеша в памяти.
`SettingsStore()` — синглтон без аргументов: повторные вызовы возвращают тот же
экземпляр и соединение. При первом вызове открывается `settings.sqlite3` в текущей
рабочей папке Python (`Path.cwd()`), файл и таблицы создаются при необходимости.
Доступ к сущности подписки — через `settings.subscription_link`. Классы
отдельных хранилищ находятся в том же файле `server/settings_store.py`.

`settings.server_settings` (`ServerSettingsStore`) хранит `ServerSettings` в таблице
`server_settings` ровно с одной строкой. Строка со значениями по умолчанию
создаётся вместе с таблицей, а `CHECK (id = 0)` не даёт добавить вторую
даже из другого соединения. `get()` возвращает текущие настройки, `save(settings)`
заменяет их. Время хранится как TEXT в ISO 8601 с `+00:00`, `outbound_tests` —
в колонке `outbound_tests` как JSON-массив объектов `{url, alias, rule}`.

```python
from dataclasses import replace
from datetime import UTC, datetime

current = settings.server_settings.get()
settings.server_settings.save(
    replace(current, last_subscription_refresh=datetime.now(UTC))
)
await context.sync.notify("server_settings")  # в хендлере: разослать клиентам
```

```python
from dataclasses import replace

from server.models import SubscriptionLink
from server.settings_store import SettingsStore

with SettingsStore() as settings:
    link = SubscriptionLink(url="https://example.com/sub")
    settings.subscription_link.save(link)  # Добавить или обновить по id.
    links = settings.subscription_link.get_all()
    saved = settings.subscription_link.get_by_id(link.id)  # SubscriptionLink | None
    settings.subscription_link.save(replace(link, url="https://example.com/new-sub"))
    deleted = settings.subscription_link.delete(link.id)  # bool
```

Каждый геттер читает актуальные данные из БД и создаёт модельные структуры.
Запись и удаление выполняются в транзакции БД; при ошибке изменения откатываются.
Одинаковый URL у разных ID запрещён: `subscription_link.save` вызывает
`sqlite3.IntegrityError`. Порядок записей сохраняется при обновлении.
Методы `subscription_link` возвращают неизменяемые модели; список можно менять без влияния на стор.

Методы синхронные. Вызывайте экземпляр из того потока, где он создан.
Изменения, сохранённые другим соединением, видны при следующем чтении.
Для завершения работы вызовите `close()` или используйте `with` на всё время
работы приложения: закрывается общее соединение для всех пользователей стора.
Следующий вызов `SettingsStore()` после закрытия создаёт новый экземпляр.
Хранение настроек не выполняет сетевую загрузку подписок.

### Загрузка подписок

`server/subscription_loader.py`, функция `load_subscription` — загрузка одной ссылки без состояния:

```python
from server.subscription_loader import load_subscription

servers = await load_subscription(subscription_url)  # list[OutboundServer]
```

`load_subscription()` принимает строковую HTTP(S)-ссылку или прямую `vless://`-ссылку
(получает новый `subscription_id`), либо
`SubscriptionLink` (используется его `id`). Прямые VLESS-ссылки разбираются без сетевого запроса;
формат ответа HTTP(S)-подписки определяется автоматически. Ошибки загрузки и разбора превращаются в
`SubscriptionError` только с id подписки, без URL и тела ответа.

Загрузка HTTP выполняется в потоке через стандартный `urllib`, не блокируя
асинхронный сервер. Таймаут — 30 секунд, User-Agent — `v2rayN/7.0`,
прокси берётся из окружения. Ответы в gzip/deflate распаковываются:
your-durev.com отдаёт gzip даже при `Accept-Encoding: identity`.
Размер ответа до и после распаковки ограничен 10 МиБ.

Проверка на реальных ссылках (файл `subscription_links.txt` в корне,
исключён из git): `LIVE_SUBSCRIPTIONS=1 python3 -m unittest server.tests.test_subscription_loader`.
Поддерживаются обычный/Base64 список VLESS URI и JSON-конфиги Xray.
Из JSON извлекаются VLESS, Shadowsocks и Hysteria 2, включая несколько outbound
и пользователей в профиле. Локальные freedom/blackhole/dns/loopback пропускаются.
Неизвестные протоколы и некорректные записи вызывают ошибку всей подписки.
Исходные настройки streamSettings сохраняются в stream_options; преобразование
моделей обратно в Xray ещё не реализовано.

`SettingsStore().outbound_server` — серверы в той же SQLite-БД.
В таблице `outbound_servers` колонки совпадают с полями `OutboundServer`:
запись и чтение строятся по `dataclasses.fields`, отдельно перечислены только
колонки, которым нужно преобразование типа при чтении. Новое поле модели
требует колонки с тем же именем. Колонки неиспользуемых протоколов содержат `NULL`. Числа и флаги хранятся как INTEGER,
UUID и enum — как TEXT. Коллекции `alpn`, `stream_options`, `extra_params`,
протокольные `extra` и результаты проверок `tests` сохраняются в собственных колонках
в формате JSON. `ping`, `speed` и `rating` — INTEGER.
Техническая колонка `profile_key` обеспечивает уникальность профиля.

Методы:

- `get_all()` возвращает все серверы; `get_by_id(id)` — сервер или `None`.
- `save(server)` добавляет сервер или обновляет по ID либо ключу профиля.
- `delete(id)` удаляет сервер и возвращает `True`, если он существовал.
- `add_servers(servers)` добавляет новые записи и обновляет совпавшие.
- `get_connected()` — сервер с `is_connected` или `None`; `set_connected(id)` снимает
  флаг со всех и ставит этому серверу, возвращает его или `None`, если сервера нет;
  `set_connected(None)` снимает флаг со всех.
- `update_health(id, ping=, speed=, rating=, tests=)` заменяет только результаты
  проверки и возвращает обновлённый сервер; остальные поля берутся из БД, поэтому
  изменения подписки, сделанные во время проверки, не затираются. Если сервера уже
  нет, ничего не записывает и возвращает `None`.
- `update_servers(servers)` полностью заменяет содержимое, удаляя отсутствующие
  записи; пустой список очищает хранилище. У совпавших профилей сохраняются
  `ping`, `speed`, `rating` и `tests`, если в новом сервере они `None`: серверы
  из подписки приходят без результатов проверок, и обновление подписок их не стирает.
  `save` и `add_servers` записывают поля как есть.

Чтение всегда идёт из БД и восстанавливает модели, UUID, enum и JSON-настройки.
Кеша нет. Изменения полученной модели сохраняются только после `save`.
Пакетные операции атомарны: при ошибке весь пакет откатывается.
При обновлении совпавшего профиля его существующий ID сохраняется, даже если
загрузчик сгенерировал новый. Переданный объект не изменяется; актуальные ID
можно получить через `get_all()`. Разные профили должны иметь разные ID.
Если ID и ключ указывают на разные сохранённые записи, `save` и `add_servers`
вызывают `sqlite3.IntegrityError`.

Ключ совпадения: **subscription_id + name + source_tag + protocol + address + port**.
Домены сравниваются без регистра/завершающей точки и в IDNA-форме,
IPv6 — в нормализованной форме. DNS не разрешается: домен и его IP не равны.
UUID, пароль, транспорт и TLS-параметры не входят в ключ, поэтому их
изменение обновляет запись. В свежезагруженной подписке смена адреса/порта создаёт новую запись; при полном
обновлении старая исчезнет. Последняя запись с одинаковым ключом побеждает,
порядок первого появления сохраняется. `update_servers` задаёт порядок по входному
списку. Явное редактирование существующего ID через `save` позволяет поменять
в том числе имя, адрес и порт этой записи.

Разные имена профилей и исходные теги сохраняются отдельно даже при совпадении
адреса и порта. Это важно для разных SNI и транспортов на одном endpoint.
Имя и тег не гарантированно стабильны: если провайдер переименовал профиль,
`add_servers` добавит новую запись, а `update_servers` удалит старую при полной
синхронизации. Без постоянного id от провайдера невозможно надёжно отличить
переименование от появления нового профиля. Если даже имя и тег совпадают,
последняя запись с тем же ключом по-прежнему считается обновлением.

```python
from server.settings_store import SettingsStore
from server.subscription_loader import load_subscription

settings = SettingsStore()
servers = settings.outbound_server

# Внутри async-функции; subscription — сохранённая модель SubscriptionLink:
servers.add_servers(await load_subscription(subscription))

# Полная синхронизация всех подписок (сначала загружаем все, затем заменяем):
loaded = []
for subscription in settings.subscription_link.get_all():
    loaded.extend(await load_subscription(subscription))
servers.update_servers(loaded)

# Для регистрации в ядре используем сохранённые ID:
registered_servers = servers.get_all()
```

Хранилища не обращаются к Xray или gRPC и не вызывают друг друга.
Приложение выполняет операции изменения последовательно.

## Проверка серверов

`handlers/outbound_test.py`, `await test_outbound(context, server)` проверяет один
сервер, записывает `ping`, `speed`, `rating`, `tests` через `update_health`
и рассылает `outbound_server`. Возвращает сохранённый сервер или `None`, если его
удалили во время проверки.

`await test_outbound_servers(context)` по очереди проверяет сохранённые серверы
через `test_outbound`, кроме отфильтрованных (раздел «Фильтрация серверов»).
`main.configure_handlers` ставит его в планировщик раз в час
(`IntervalTrigger(hours=1)`, id `test_outbound_servers`); первый запуск — через час
после старта. Это долгая задача: если прошлый проход ещё идёт, новый не запускается,
пока идёт `refresh_subscriptions` — пропускается, а начало обновления подписок
или остановка приложения прерывают проход. Прерванная проверка освобождает тестовый
inbound (`test_stop` в `finally`), её результаты не записываются; результаты уже
проверенных серверов сохранены.
Список id берётся в начале прохода: удалённый за это время сервер пропускается,
изменённый проверяется с текущими параметрами из БД. Ошибка проверки одного сервера
(например, он не зарегистрирован в ядре) пишется в лог с id сервера, проход
продолжается.

Условие вызова: ядро запущено и сервер в нём зарегистрирован. Приложение делает
это на старте и после каждого обновления подписок. `test_connect` только переключает тестовый inbound
на зарегистрированный сервер, а `outbound_register` сбрасывает и основной маршрут,
поэтому хендлер сам серверы не регистрирует.

1. **Пинг.** Время TCP-подключения к `address:port`, лучшее из 3 попыток; DNS
   разрешается заранее и в пинг не входит. Попытка дольше 500 мс прерывается.
   Если ни одна не уложилась, проверка заканчивается: `ping = None`,
   `speed = None`, все тесты `False`, `rating = 0`, `filtered = BY_PING`;
   иначе `BY_PING` снимается. Серверы не на TCP
   (Hysteria работает поверх QUIC/UDP) не пингуются: `ping = None`, проверка идёт дальше.
2. **Тестовый inbound.** `test_connect(server.id)`, дальше все запросы идут через
   SOCKS5 `127.0.0.1:test_port`. Inbound один, поэтому проверки разных серверов ждут
   друг друга на `context.outbound_test_lock`; пинг идёт без лока и может выполняться
   параллельно. После шагов 3–4 всегда вызывается `test_stop()`, даже при ошибке.
3. **Скорость.** Скачивается файл ровно 250 000 байт (1 Мбит/с × 2 с) с
   `speed.cloudflare.com/__down`. Скорость не ограничивается, зато трафик не больше
   этого объёма. Отсчёт идёт с получения заголовков ответа, чтение прекращается
   через 2 с или после 250 000 байт, соединение закрывается. `speed` — байт в секунду;
   при ошибке или статусе не 200 — 0.
4. **Тесты.** `ServerSettings.outbound_tests` по очереди: GET по `url`, статус
   сравнивается с `rule`. Редиректы не выполняются, тело не скачивается. Нет ответа
   за 5 с, ошибка TLS или соединения — `False`.

Все запросы идут через новое соединение (без keep-alive), имена сайтов разрешает
прокси, переменные окружения `HTTP(S)_PROXY` не используются. Работа асинхронная
и не блокирует event loop. HTTP и SOCKS5 — библиотеки `aiohttp` и `aiohttp-socks`.

**Рейтинг** — целое число 0–100, если сервер ответил на пинг:

| часть | вес | оценка от 0 до 1 |
| --- | --- | --- |
| пинг | 30 | `1 − ping / 500` |
| скорость | 30 | `min(speed / 125 000, 1)`: от 1 Мбит/с — полный балл |
| тесты | 40 | доля пройденных |

`rating = round(100 × Σ(вес × оценка) / Σ весов)` по измеренным частям. Части,
которые не измерялись, в сумму не входят, и остальные занимают их вес: серверы
без пинга (не TCP) и настройки без тестов баллов не теряют.

Константы — в `outbound_probe.py` (`PING_ATTEMPTS`, `PING_LIMIT`, `SPEED_TEST_URL`,
`SPEED_TEST_BYTES`, `SPEED_TEST_DURATION`, `REQUEST_TIMEOUT`) и в
`handlers/outbound_test.py` (веса рейтинга).

## Интерфейсы ядер

В `server/cores/core_process_manager.py` расположен абстрактный класс
`CoreProcessManagerInterface`: `api_port`, `binary_path`, `status()`, `start()` и `stop()`.

Менеджер `XrayProcessManager` наследуется от этого интерфейса.
Реализация менеджера и самостоятельный `XrayGrpcClient` находятся в `server/cores/xray/`.
Там же расположена папка `grpc_generated`; генератор в `scripts/generate_grpc.py`
записывает результат в неё. Менеджер процесса и клиент независимы.

## Клиент приложения

`server/cores/core_client.py` содержит абстрактный `CoreClient`.
`server/cores/xray/xray_client.py` реализует его классом `XrayClient`, который
использует отдельные `XrayProcessManager` и `XrayGrpcClient`.

```python
from server.cores.xray.xray_client import XrayClient

client = XrayClient()
await client.service_start(proxy_port=1080, test_port=1081)
try:
    await client.outbound_register([selected_server, candidate_server, another_server])
    await client.outbound_connect(selected_server.id)
    await client.test_connect(candidate_server.id)
    # Свои HTTP-запросы через SOCKS5 127.0.0.1:1081.
    await client.outbound_connect(another_server.id)
    await client.test_stop()
finally:
    await client.service_stop()
```

- Все операции нужно вызывать последовательно из одного event loop.
- `check_outbound_server_config(server)` — синхронная проверка параметров сервера
  ядром: собирает конфиг этого ядра и вызывает `ValueError`, если не может. Не ходит
  в сеть, не требует запущенного ядра и ничего не меняет. Работоспособность сервера
  проверяет приложение (раздел «Проверка серверов»), а не клиент ядра.
- SOCKS5 слушает только `127.0.0.1`, без аутентификации, с поддержкой UDP.
  Порты задаются явно в диапазоне 1–65535. Текущие порты доступны в
  `proxy_port` и `test_port`; `test_port` объявлен в интерфейсе `CoreClient`
  (`None`, пока сервис остановлен).
- Без выбранного outbound трафик соответствующего inbound блокируется.
  Оба listener создаются при запуске. `test_connect` задаёт маршрут,
  но не выполняет сетевую проверку сервера.
- `outbound_register` полностью заменяет список, сбрасывая оба маршрута в блокировку.
  `outbound_connect(id)` и `test_connect(id)` выбирают уже зарегистрированный сервер.
  Переключение не удаляет остальные регистрации. Xray проверяет наличие ID через gRPC.
- `test_stop` блокирует тестовый маршрут, сохраняя listener и серверы. Повторный
  `test_connect(id)` возобновляет маршрутизацию новых соединений. Уже открытые
  соединения не переносятся на другой сервер и не закрываются принудительно.
- Порты фиксируются при `service_start(proxy_port, test_port)`. Методы `change_port`
  и `test_start` удалены из интерфейса; смена портов выполняется остановкой и запуском.
- Клиент управляет всей таблицей правил. Не изменяйте её параллельно через
  низкоуровневый gRPC-клиент. `service_start` требует остановленного сервиса;
  `service_stop` закрывает gRPC и останавливает процесс.
- `outbound_config.py` объединяет поля модели и `stream_options` в словарь
  в памяти. Явные поля модели имеют приоритет. Неизвестные параметры URI
  в `extra_params` сохраняются в модели, но не интерпретируются клиентом.
- `outbound_protobuf.py` собирает `OutboundHandlerConfig`, `SenderConfig`,
  настройки протокола и транспорта непосредственно через Python protobuf.
  Сборка синхронная: нет файлов, запуска `xray convert pb` и перезапуска ядра.
  Готовый объект передаётся через `XrayGrpcClient.add_outbound()`.
- Поддерживаются VLESS, Shadowsocks (включая 2022), Hysteria 2;
  TCP, WS, gRPC, XHTTP, Hysteria; TLS и Reality. В XHTTP преобразуются
  диапазоны и `extra.xmux`, в Reality — ключи, short ID и `spiderX`,
  в Hysteria — `finalmask.quicParams`. Shadowsocks UoT поддерживается
  только для 2022, как в используемой версии ядра.
- Это преобразователь клиентских настроек, а не полная реализация всех
  расширений JSON Xray. Неподдерживаемые поля (например TCP/UDP-маски,
  сертификаты TLS из файлов) вызывают `ValueError` до изменения маршрута.
  Неизвестные поля не отбрасываются незаметно. Новые расширения требуют
  явного добавления преобразования и тестов.

Локальные тесты проверяют SOCKS-handshake, независимость маршрутов,
смену портов, удаление прежних outbound и конвертацию VLESS/Shadowsocks/Hysteria 2,
а также TCP/WS/gRPC/XHTTP. Доступность реальных серверов подписок эти тесты
не проверяют.
