# Docker

Образ содержит сервер, собранный веб-интерфейс и Mihomo. Он собирается для
`linux/amd64` и `linux/arm64` и хранится в GitHub Container Registry:
`ghcr.io/s-vin/x-proxy-router`.

| Файл | Назначение |
| --- | --- |
| `Dockerfile` | Сборка образа из корня репозитория. |
| `Dockerfile.dockerignore` | Что попадает в сборку. Базы, `subscription_links.txt` и `.env` в неё не попадают. |
| `entrypoint.sh` | Проверяет `XPR_UI_PORT` и папку `/data`, затем запускает сервер. |
| `compose.yaml` | Запуск на сервере. |
| `.env.example` | Шаблон переменных для `compose.yaml`. |

## Сборка образа

Образ собирает workflow «Docker image» (`.github/workflows/docker.yml`). Он
запускается только вручную: **Actions → Docker image → Run workflow**, затем
выбрать ветку. Образ получает теги:

- `latest` — только при сборке из основной ветки;
- имя ветки, например `master`;
- `sha-<коммит>`, например `sha-1a2b3c4`, чтобы можно было вернуться к прежней сборке.

Пакет приватного репозитория тоже приватный. Чтобы скачать его на сервере, нужно
сначала войти в реестр с [personal access token (classic)](https://github.com/settings/tokens)
с правом `read:packages`:

```sh
echo <токен> | docker login ghcr.io -u <логин GitHub> --password-stdin
```

Пакет можно сделать публичным: **Package settings → Change visibility**. Тогда вход
не нужен.

Собрать образ локально можно из корня репозитория:

```sh
docker build -f docker/Dockerfile -t ghcr.io/s-vin/x-proxy-router:latest .
```

## Запуск на сервере

Нужны Linux и Docker с плагином `compose`. На сервер достаточно скопировать
`compose.yaml` и `.env.example` в одну папку:

```sh
cp .env.example .env    # задать XPR_UI_PORT и XPR_DATA_DIR
docker compose pull
docker compose up -d
```

Интерфейс откроется по адресу `http://<адрес сервера>:<XPR_UI_PORT>/`.

### Переменные

| Переменная | Обязательна | По умолчанию | Назначение |
| --- | --- | --- | --- |
| `XPR_UI_PORT` | да | — | Порт веб-интерфейса. |
| `XPR_DATA_DIR` | да | — | Папка на сервере для настроек (`settings.sqlite3`), в контейнере это `/data`. Docker создаст её, если её нет. |
| `XPR_UI_HOST` | нет | `0.0.0.0` | IP-адрес веб-интерфейса. `0.0.0.0` — все IPv4-адреса сервера, `127.0.0.1` — только сам сервер. |

Если обязательная переменная не задана, `docker compose` не запустит контейнер и
назовёт её. Без `compose` образ проверяет то же сам: нужны `XPR_UI_PORT` и папка
хоста в `/data`, иначе контейнер завершится с сообщением.

```sh
docker run -d --name x-proxy-router --restart unless-stopped --network host \
  -e XPR_UI_PORT=20800 -v /srv/x-proxy-router:/data \
  ghcr.io/s-vin/x-proxy-router:latest
```

### Сеть

Контейнер использует сеть сервера (`network_mode: host`). Поэтому inbound,
добавленный в интерфейсе, сразу слушает выбранный порт на сервере, UDP тоже
работает, и порты не нужно перечислять в `compose.yaml`. На сервере заняты:

- `XPR_UI_PORT`;
- `127.0.0.1:20809` для проверки серверов;
- случайный порт API Mihomo на `127.0.0.1`;
- порты inbound-ов.

Inbound, созданный при первом запуске (`127.0.0.1:20808`), доступен только на самом
сервере. Чтобы подключаться к нему с других машин, в блоке Inbounds выберите
«Local network» и включите логин. Без логина прокси сможет пользоваться любой, кто
достучится до порта.

У веб-интерфейса нет авторизации. Любой, кто откроет `XPR_UI_PORT`, управляет
роутером и видит ссылки подписок. Ограничьте доступ к порту файрволом или VPN.
Другой вариант — задать `XPR_UI_HOST=127.0.0.1` и открывать интерфейс через
SSH-туннель:

```sh
ssh -L 20800:127.0.0.1:<XPR_UI_PORT> <пользователь>@<сервер>
# затем открыть http://localhost:20800/
```

## Обновление, логи, резервная копия

```sh
docker compose pull && docker compose up -d   # обновить до свежего latest
docker compose logs -f                         # логи; хранятся 3 файла по 10 МБ
```

Все настройки хранятся в одном файле `settings.sqlite3` в `XPR_DATA_DIR`. Для
резервной копии остановите контейнер (`docker compose stop`), скопируйте файл и
запустите контейнер снова (`docker compose start`).
