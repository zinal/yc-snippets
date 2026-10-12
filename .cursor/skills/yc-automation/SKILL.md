---
name: yc-automation
description: Пишет скрипты, которые создают, изменяют или удаляют ресурсы Yandex Cloud. Use when automating Yandex Cloud changes, yc create/update/delete, or operational scripts beyond read-only inventory.
---

# Изменяющие скрипты Yandex Cloud

Инвентаризация остаётся в `python scripts/yc-snippets inventory`. Скрипт, который меняет облако, клади в `scripts/automation/` и следуй `scripts/automation/README.md`.

## Обязательный каркас

- Аргументы: `--folder-id` или id ресурса, имя, и `--dry-run`.
- В `--dry-run` печатай точную команду `yc` и выходи до вызова, который создаёт, меняет или удаляет.
- Собирай argv через тот же запрет, что в `yc_snippets.plan.assert_safe_argv`: никаких `--token` и `--service-account-key`.
- Имперсонация — только `--impersonate-service-account-id` с идентификатором, если пользователь его дал.
- Удаление требует отдельный аргумент с id или именем одной цели. Не удаляй «все ресурсы из файла инвентаризации» одним запуском.
- После `create` и `update` дождись операции (`yc operation wait <id>`), если CLI вернул operation id. Не считай ресурс готовым по факту отправки запроса.
- Id облака и каталога не зашивай в файл. Пример в документации CLI помечай как пример.

Пока пользователь не попросил выполнить изменение, остановись на `--dry-run` и покажи команду.

## Где проверять форму команды

`yc <группа> <ресурс> <действие> --help` или proto в <https://github.com/yandex-cloud/cloudapi>. Имя ресурса и флаг не переноси из другого сервиса: у ClickHouse, PostgreSQL и Compute разные команды.

Роли на изменение шире, чем `viewer`. Не расширяй права скриптом; если не хватает роли, остановись и напиши, какая операция отказала.
