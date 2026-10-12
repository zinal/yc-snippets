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

## Обновить каталог после новой версии yc

```bash
python scripts/refresh_catalog.py
python -m pytest
```

## Агентам

Правила работы лежат в [`AGENTS.md`](AGENTS.md), в [`.cursor/rules/yc-snippets.mdc`](.cursor/rules/yc-snippets.mdc) и в скиллах [`.cursor/skills/`](.cursor/skills):

- `yc-inventory` — сбор и новые команды списка
- `yc-automation` — скрипты, которые создают или удаляют ресурсы
- `yc-public-sources` — сверка с документацией и обновление каталога

Проверка без облака: `python -m pip install pytest` и затем `python -m pytest`.
