---
name: yc-public-sources
description: Сверяет работу с официальными материалами Yandex Cloud и обновляет каталог команд yc. Use when checking Yandex Cloud docs, APIs, SDK, CLI reference, or refreshing the yc list catalog.
---

# Публичные источники Yandex Cloud

Прочитай `docs/public-sources.md`. Для входа в CLI дополнительно открой `docs/auth.md`.

## Что считать источником

1. Локальная справка установленного `yc` для argv и флагов.
2. [Справочник CLI](https://yandex.cloud/ru/docs/cli/cli-ref/) и страница сервиса на <https://yandex.cloud/ru/docs/>.
3. Proto в <https://github.com/yandex-cloud/cloudapi>, если нужны поля ответа или метод `List`.
4. README [python-sdk](https://github.com/yandex-cloud/python-sdk), если скрипт идёт мимо CLI. Пакет `yandexcloud` в этот репозиторий не входит.

Не копируй в репозиторий большие фрагменты документации. Достаточно ссылки и того факта, который нужен скрипту.

## Обновление каталога

Каталог `src/yc_snippets/data/inventory.json` — снимок `yc --help`, не рукописный перечень.

```bash
python scripts/refresh_catalog.py
python -m pytest
```

После обновления CLI проверь, что новые команды с паролями, ключами и `scope=parent` не стали `default: true`. Сервисы с Amazon-совместимым API (очереди, часть уведомлений) в этом снимке отсутствуют: для них смотри раздел сервиса в документации, а не добавляй несуществующую команду `yc`.

Счета биллинга в CLI 1.41.0 не перечисляются командой `list`. Не придумывай `yc billing account list`, пока `yc billing --help` её не покажет.
