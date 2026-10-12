# Публичные материалы Yandex Cloud

Это указатель официальных источников, на которые опираются скрипты и агенты.
Тексты документации в репозиторий не копируются: команды `list` сняты со справки
установленного CLI и лежат в `src/yc_snippets/data/inventory.json`.

Снимок каталога: Yandex Cloud CLI 1.41.0, 2026-10-12.
Страница групп CLI на эту дату: <https://yandex.cloud/en/docs/cli/cli-ref/>.

## Иерархия ресурсов

Организация → облако → каталог (folder) → ресурсы сервиса.

Идентификаторы ресурсов глобальные. Имя уникально только внутри каталога, поэтому
скрипты обращаются к ресурсам по id. Облако и каталог по умолчанию задаются в
профиле `yc` и переопределяются флагами `--cloud-id` и `--folder-id`.

## Документация и контракты API

| Материал | Зачем |
| --- | --- |
| [Документация, ru](https://yandex.cloud/ru/docs/) | Описание сервисов и ролей |
| [Документация, en](https://yandex.cloud/en/docs/) | То же на английском |
| [Быстрый старт CLI](https://yandex.cloud/ru/docs/cli/quickstart) | Установка `yc` |
| [Как выполнять команды](https://yandex.cloud/en/docs/cli/concepts/) | Глобальные флаги, доступ по имени и по id |
| [Справочник CLI](https://yandex.cloud/ru/docs/cli/cli-ref/) | Группы команд |
| [Обзор API](https://yandex.cloud/ru/docs/api-design-guide/) | REST, gRPC, операции, страницы |
| [cloudapi](https://github.com/yandex-cloud/cloudapi) | Proto-контракты, источник правды для полей |
| [Resource Manager API](https://yandex.cloud/en/docs/resource-manager/api-ref/) | Облака и каталоги. Хост `resource-manager.api.cloud.yandex.net` |
| [Compute API](https://yandex.cloud/en/docs/compute/api-ref/) | Виртуальные машины, диски, образы. Хост `compute.api.cloud.yandex.net` |
| [VPC API](https://yandex.cloud/en/docs/vpc/api-ref/) | Сети, подсети, группы безопасности, адреса |

Список ресурсов почти у всех сервисов устроен одинаково: `folder_id` или id
родителя, `page_size` не больше 1000, ответ с `next_page_token`. CLI сам
перелистывает страницы до `--limit` (по умолчанию 1000). Если ресурсов больше,
увеличьте `--limit` у `python scripts/yc-snippets inventory`.

## SDK и другие инструменты

| Инструмент | Когда брать |
| --- | --- |
| `yc` | Сбор метаданных и короткие операции. Основной путь этого репозитория |
| [yandexcloud](https://github.com/yandex-cloud/python-sdk) / [PyPI](https://pypi.org/project/yandexcloud/) | Скрипт на Python, ожидание операций, свой фильтр. Пакет ставится отдельно |
| [go-sdk](https://github.com/yandex-cloud/go-sdk) | То же на Go |
| [terraform-provider-yandex](https://github.com/yandex-cloud/terraform-provider-yandex) | Описание желаемого состояния, не инвентаризация |

Python SDK поднимает клиент так: метаданные виртуальной машины, ключ сервисного
аккаунта или готовый IAM-токен. Имена gRPC-сервисов и алиасы эндпоинтов
перечислены в README репозитория SDK. Повторяющееся поле ответа (`instances`,
`networks`, `clouds`) у каждого `List` своё; его имя нужно смотреть в proto, а
не угадывать.

Регион по умолчанию — `api.cloud.yandex.net`. Для другого региона SDK принимает
`endpoint`, например `api.yandexcloud.kz`.

## Сервисы вне дерева `yc ... list`

У части сервисов HTTP API совместим с Amazon, и в CLI 1.41.0 нет обычной
команды `list`. Их не нужно дописывать в каталог как выдуманную подкоманду.

- [Object Storage](https://yandex.cloud/ru/docs/storage/) есть и в `yc storage bucket list`, и через AWS CLI. Эндпоинт по умолчанию `storage.yandexcloud.net`.
- [Message Queue](https://yandex.cloud/ru/docs/message-queue/) — API, совместимый с Amazon SQS.
- Сервисы вроде Postbox и Notification Service ходят через совместимый HTTP API. Перед скриптом сверьтесь с разделом сервиса в документации.

Группы `yc`, которые CLI 1.41.0 показывает в корневой справке: adviser,
application-load-balancer, audit-trails, backup, baremetal, billing, cdn,
certificate-manager, cic, cloud-registry, cloudrouter, compute, container,
dataproc, datatransfer, desktops, dns, iam, iot, kms, load-balancer, lockbox,
logging, managed-airflow, managed-clickhouse, managed-gitlab, managed-greenplum,
managed-kafka, managed-kubernetes, managed-metastore, managed-mongodb,
managed-mysql, managed-opensearch, managed-postgresql, managed-redis,
managed-sharded-postgresql, managed-spark, managed-trino, managed-ytsaurus,
managed-zonalshift, marketplace, metadata-hub, organization-manager,
quota-manager, resource-manager, serverless, smartcaptcha, smartwebsecurity,
storage, vpc, ydb. У billing в этой версии нет команды `account list`; счета
нужно брать из API биллинга отдельно.
