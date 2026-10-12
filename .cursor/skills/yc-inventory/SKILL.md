---
name: yc-inventory
description: Собирает метаданные ресурсов Yandex Cloud и добавляет команды инвентаризации. Use when listing, exporting, or inventorying Yandex Cloud resources, folders, clouds, or yc list output.
---

# Инвентаризация Yandex Cloud

Сначала прочитай `docs/inventory.md` и запись команды в `src/yc_snippets/data/inventory.json`. Каталог — источник argv. Если команды там нет, её ещё нельзя вызывать.

## Запуск

```bash
python scripts/yc-snippets catalog list --default
python scripts/yc-snippets inventory --dry-run --folder-id <folder-id> --only compute.instance,vpc.subnet
python scripts/yc-snippets inventory --out ./out --folder-id <folder-id>
```

Без `--folder-id` раннер обходит все видимые облака и каталоги. `--dry-run` сеть не трогает. Профиль берётся из `--profile` или `YC_PROFILE`. Токен в команду не добавляй.

Результат — конверт на команду и `out/summary.json`. Ошибка прав у одного сервиса остаётся в его конверте, обход продолжается.

## Что не собирать в обычном прогоне

- `sensitivity=secret`: пароли, refresh-токены, секреты OAuth. Флаг `--allow-secrets` не ставь, пока пользователь прямо не попросил именно эти объекты.
- Payload Lockbox, `yc config list`, закрытые ключи.
- `scope=parent`, пока нет id родителя. У записи есть `parent_command` и `parent_flag`: сначала собери родителя, из его JSON возьми поле `id`, затем вызови дочернюю команду с этим флагом.
- Справочники и обслуживание включаются только флагами `--include-reference` и `--include-operational`.

`lockbox.secret` в обычном прогоне допустим: это список метаданных, не значение секрета.

## Как добавить ресурс

1. Убедись, что команда есть в справке: `yc <группа> <ресурс> list --help`.
2. Обнови снимок: `python scripts/refresh_catalog.py`.
3. В diff проверь `default`, `scope`, `sensitivity`. Справочник или секрет не должны получить `default: true`.
4. Если классификатор ошибся, исправь `src/yc_snippets/classify.py`, пересобери каталог и дополни `tests/test_classify.py`.
5. Запусти `python -m pytest`.

Не дописывай argv вручную в обход `build_argv`. Лимит страницы CLI — `--limit`; сам раннер подставляет его только тем командам, у которых флаг есть в каталоге.
