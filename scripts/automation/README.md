# Скрипты, которые меняют ресурсы

Сюда попадают операции создания, изменения и удаления. Сбор метаданных остаётся
в `python scripts/yc-snippets inventory`.

У такого скрипта есть `--dry-run`, и в этом режиме он не вызывает изменяющих
команд. Идентификатор каталога и имя ресурса приходят аргументами. Токен и файл
ключа в argv не передаются. Удаление требует отдельного аргумента с именем или
id ресурса и не запускается пакетом «всё, что нашлось».

## Флейвор, зона и размер инстанс-группы

```bash
python scripts/automation/adjust-instance-group.py \
  --instance-group-id <instance-group-id> \
  --zone ru-central1-d \
  --platform standard-v4a \
  --cores 8 \
  --memory-gb 32 \
  --size 6 \
  --spec ./group.yaml \
  --dry-run
```

`--dry-run` печатает `yc compute instance-group get --full` и
`yc compute instance-group update <id> --file` и не вызывает `yc`. Без
`--dry-run` скрипт записывает вывод `get` в `--spec`, подставляет
`instance_template.platform_id`, число ядер, память (гигабайты по 1024³ байт),
`scale_policy.fixed_scale.size` и единственную зону в `allocation_policy.zones`,
удаляет поля ответа, которых нет в `UpdateInstanceGroupRequest`, и применяет
файл. `--async` не передаётся: CLI дожидается операции сам.
