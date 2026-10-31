# yc-snippets

Скрипты для Yandex Cloud: сбор метаданных ресурсов, которые уже созданы в облаке, и место для операций, которые эти ресурсы меняют.

Каталог команд снят со справки Yandex Cloud CLI 1.41.0 и лежит в [`src/yc_snippets/data/inventory.json`](src/yc_snippets/data/inventory.json). Официальные документы, SDK и сервисы без команды `list` собраны в [`docs/public-sources.md`](docs/public-sources.md).

## Что нужно

- Python 3.11+
- [Yandex Cloud CLI](https://yandex.cloud/ru/docs/cli/quickstart)

Учётные данные читает сам `yc` из профиля. Скрипт не принимает токен аргументом. Способы входа описаны в [`docs/auth.md`](docs/auth.md).

## Сбор ресурсов

```bash
python scripts/yc-snippets catalog list --default
python scripts/yc-snippets inventory --dry-run --folder-id <folder-id> --only compute.instance,vpc.subnet
python scripts/yc-snippets inventory --out ./out --folder-id <folder-id>
```

Без `--folder-id` обходятся все видимые облака и каталоги. `--dry-run` только печатает команды. Результат появляется в `./out` как JSON на каждую команду и общий `summary.json`. Подробности — в [`docs/inventory.md`](docs/inventory.md).

По умолчанию собираются метаданные созданных ресурсов: виртуальные машины, диски, сети, кластеры, бакеты, функции, сервисные аккаунты и остальные команды каталога с `default: true`. Справочники, пароли, пользователи организации и объекты, которым нужен id родителя, в этот прогон не входят.

## Базы YDB по списку путей

Файл `databases.txt`, одна строка — путь `/ru-central1/<cloud-id>/<database-id>`:

```bash
python scripts/export-ydb.py databases.txt --federation-id <federation-id> --out ./out/ydb
```

Команда открывает браузер через `yc init --federation-id`. Для каждой базы пишется JSON с описанием, правами, резервными копиями каталога и связанными облаком, каталогом, сетью и пресетом. Содержимое таблиц не читается. Повторный запуск, пока токен федерации жив: `--skip-init`.

Инстанс-группа с именем `instance-group-<database-id>` из уже записанной выгрузки:

```bash
python scripts/export-instance-groups.py --folder-id <folder-id> --out ./out/ydb
```

`--folder-id` — каталог, в котором лежат группы. Для каждой базы рядом с её JSON появляется файл `<cloud-id>__<database-id>.instance-group.json`: статус группы, полное описание (`instance-group get --full`), текущий список машин и их размещение по зонам. `--dry-run` только печатает команды. Профиль по умолчанию тот же, `ydb-export`.

## Обновить каталог после новой версии yc

```bash
python scripts/refresh_catalog.py
python -m pytest
```

## Прокси Squid на Ubuntu 26.04

Установка прямого прокси без логина для сети `192.168.0.0/16`, пример
`/etc/squid/conf.d/`, настройка клиента для `apt-get` и команды
`ansible-console` для группы серверов — в
[`docs/squid-ubuntu-26.04.md`](docs/squid-ubuntu-26.04.md).

## Агентам

Правила работы лежат в [`AGENTS.md`](AGENTS.md), в [`.cursor/rules/yc-snippets.mdc`](.cursor/rules/yc-snippets.mdc) и в скиллах [`.cursor/skills/`](.cursor/skills):

- `yc-inventory` — сбор и новые команды списка
- `yc-automation` — скрипты, которые создают или удаляют ресурсы
- `yc-public-sources` — сверка с документацией и обновление каталога

Проверка без облака: `python -m pip install pytest` и затем `python -m pytest`.
