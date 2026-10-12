# Инвентаризация

Раннер вызывает `yc <группа> <ресурс> list --format json` по каталогу
`src/yc_snippets/data/inventory.json` и складывает ответ в JSON-конверт.
Каталог собран из `yc --help` скриптом `scripts/refresh_catalog.py`, без
обращения к API.

## Области

| `scope` | Что делает раннер |
| --- | --- |
| `account` | Один раз. Так читаются облака и организации |
| `cloud` | Один раз на облако, с `--cloud-id` |
| `folder` | Один раз на каталог, с `--folder-id` |
| `organization` | Один раз на организацию. В прогон по умолчанию не входит |
| `parent` | Не выполняется. Нужен id родителя, например `--cluster-id` |

Без `--folder-id` раннер сам получает облака и каталоги. С `--folder-id` обходит
только этот каталог. `--cloud-id` оставляет одно облако.

В прогон по умолчанию попадают команды с `kind=resource`, `sensitivity=none` и
областью, которую раннер умеет обойти. Справочники (зоны, типы дисков, версии
СУБД), обслуживание, рекомендации Adviser, пользователи организации и
метаданные ключей выключены. Их включают флагами `--include-reference`,
`--include-operational`, `--include-advisory`, `--include-pii`,
`--include-credentials`.

Команды с `sensitivity=secret` (пароли IoT, refresh-токены, секреты OAuth-клиентов)
не запускаются без `--allow-secrets`. Для учёта ресурсов этот флаг не нужен.
`yc lockbox secret list` входит в обычный прогон и возвращает метаданные секрета.
`yc lockbox payload get` раннер не вызывает.

Вложенная команда хранит `parent_command` и `parent_flag`, если родителя удалось
однозначно сопоставить. Пример: `managed-postgresql.hosts` ждёт `--cluster-id`
из `managed-postgresql.cluster`. Чтобы собрать хосты, нужен отдельный проход по
уже собранным кластерам, а не ещё один вызов на каталог.

## Запуск

```bash
python scripts/yc-snippets catalog list --default
python scripts/yc-snippets inventory --dry-run --folder-id b1gfolder --only compute.instance,vpc.subnet
python scripts/yc-snippets inventory --out ./out
```

`--dry-run` не вызывает `yc`. Недостающий id печатается как `$FOLDER_ID`,
`$CLOUD_ID` или `$ORGANIZATION_ID`.

Каталог `./out`:

```text
out/summary.json
out/account/resource-manager.cloud.json
out/clouds/<cloud-id>/resource-manager.folder.json
out/folders/<folder-id>/compute.instance.json
```

Конверт:

```json
{
  "id": "compute.instance",
  "scope": "folder",
  "scope_id": "b1g...",
  "collected_at": "2026-10-12T00:00:00+00:00",
  "command": ["yc", "compute", "instance", "list", "--format", "json", "--folder-id", "b1g..."],
  "ok": true,
  "resources": []
}
```

Ошибка сервиса или нехватка прав не обрывает обход. Если список каталогов одного облака недоступен, остальные облака всё равно читаются. Без списка облаков обход начать нельзя. Текст stderr проходит через
маскирование IAM-токенов, OAuth-токенов и блоков private key. В поле `command`
нет `--token` и пути к ключу.

`--limit` по умолчанию 1000 и добавляется только командам, у которых такой флаг
есть. Это потолок одной выборки CLI.

## Как добавить ресурс

1. Поставьте нужную версию `yc`.
2. Запустите `python scripts/refresh_catalog.py`.
3. Просмотрите diff каталога: не включилась ли команда, которая читает секрет или требует id родителя.
4. Запустите `python -m pytest`.

Ручная правка `inventory.json` допустима только если `yc <команда> list --help`
подтверждает argv. Новую подкоманду нельзя выводить из названия сервиса.
Если после обновления CLI классификатор ошибся, правьте правила в
`src/yc_snippets/classify.py` и пересобирайте каталог, а не один JSON-объект.
