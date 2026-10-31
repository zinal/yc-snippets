# Squid на Ubuntu 26.04

Прямой HTTP-прокси без аутентификации для клиентов из `192.168.0.0/16`
(адреса `192.168.*`). `localhost` по-прежнему разрешён правилами поставки.
Любой другой источник получает отказ.

Пакет в Ubuntu 26.04 LTS (resolute) — `squid` `7.2-2ubuntu2.2` из `main`
на amd64 и arm64. Это сборка с GnuTLS. Отдельный пакет `squid-openssl`
для этой схемы не нужен: HTTPS-клиент открывает туннель `CONNECT` на порт 443,
прокси не расшифровывает трафик.

Анонимный доступ здесь значит, что клиент не вводит логин и пароль.
Адрес клиента пишется в `/var/log/squid/access.log`. Для обычного HTTP
Squid по умолчанию добавляет заголовок `X-Forwarded-For`.

## Установка

```bash
sudo apt update
sudo apt install squid
```

Пакет сам создаёт кэш и запускает службу `squid`. Порт по умолчанию — TCP `3128`
на всех интерфейсах. Доступ снаружи режут правила ниже: в поставке разрешён
только `localhost`.

Сохраните исходный файл, чтобы было с чем сравнить:

```bash
sudo cp -a /etc/squid/squid.conf /etc/squid/squid.conf.original
sudo chmod a-w /etc/squid/squid.conf.original
```

## Файл правил

Пример — [`examples/squid/conf.d/allow-192-168.conf`](../examples/squid/conf.d/allow-192-168.conf).
Команда ниже запускается из корня этого репозитория. На сервере без копии
репозитория создайте тот же путь и запишите в него эти строки:

```
acl lan_192_168 src 192.168.0.0/16
http_access allow lan_192_168
```

Рядом уже лежит поставленный `/etc/squid/conf.d/debian.conf`:

```bash
sudo install -m 644 examples/squid/conf.d/allow-192-168.conf /etc/squid/conf.d/allow-192-168.conf
```

Имя обязано заканчиваться на `.conf`: в `squid.conf` пакета Ubuntu строка

```
include /etc/squid/conf.d/*.conf
```

стоит в блоке `http_access` сразу после комментария
`INSERT YOUR OWN RULE(S) HERE TO ALLOW ACCESS FROM YOUR CLIENTS`
и до `http_access deny all`. К этому моменту уже действуют запреты:

- запросы на порты вне `Safe_ports`;
- `CONNECT` куда-либо кроме `SSL_ports` (443);
- доступ к службам на самом прокси через `to_localhost` (`127.0.0.0/8`, `::1`);
- доступ к link-local адресам через `to_linklocal`, включая `169.254.169.254`.

Поэтому фрагмент в `conf.d` разрешает сеть `192.168.0.0/16` и не открывает
эти направления. Вставлять `http_access allow` выше этих строк в `squid.conf`
не нужно.

Строку `http_access allow localnet` оставьте закомментированной и в
`/etc/squid/squid.conf`, и в `/etc/squid/conf.d/debian.conf`. ACL `localnet`
в поставке включает `0.0.0.0/8`, `10.0.0.0/8`, `100.64.0.0/10`, `169.254.0.0/16`,
`172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7` и `fe80::/10`.

Узкая подсеть вместо всей `192.168.0.0/16` задаётся в том же файле, например
`acl lan_192_168 src 192.168.1.0/24`.

Проверка синтаксиса и применение:

```bash
sudo squid -k parse
sudo systemctl reload squid
sudo systemctl status squid --no-pager
```

`squid -k parse` завершается с кодом 0, когда файл разобран. Ошибка синтаксиса
в журнале: `journalctl -u squid -n 50`.

## Фаервол

Служба слушает `3128` на всех адресах машины. Второй контур — входящий TCP
только из `192.168.0.0/16`.

UFW:

```bash
sudo ufw allow from 192.168.0.0/16 to any port 3128 proto tcp
sudo ufw reload
sudo ufw status
```

Профиль приложения в `/etc/ufw/applications.d/squid` открывает порты прокси
без ограничения источника. Для этой схемы используйте правило с
`from 192.168.0.0/16`.

Если у машины есть публичный адрес или она в облаке, входящий TCP `3128`
в группе безопасности тоже ограничьте источником `192.168.0.0/16`.

## Клиент

Ниже адрес прокси — `192.168.0.10`. Подставьте адрес машины со Squid в сети
`192.168.*`. Порт — `3128`, логин пустой.

Разовая проверка с клиента из `192.168.0.0/16`:

```bash
curl -x http://192.168.0.10:3128 -I http://example.com
curl -x http://192.168.0.10:3128 -I https://example.com
```

Оба запроса получают ответ сайта. В `/var/log/squid/access.log` строка с
`TCP_TUNNEL` для HTTPS и с кодом HTTP для обычного запроса.

С адреса вне `192.168.0.0/16` тот же `curl` получает отказ Squid
(`ERR_ACCESS_DENIED`, HTTP 403), если порт вообще доступен. При закрытом
фаерволе соединение обрывается до HTTP.

`curl` на самом прокси через `127.0.0.1:3128` проходит по правилу
`http_access allow localhost` из поставки и не проверяет ACL `lan_192_168`.
Сеть `192.168.0.0/16` проверяйте с клиента из этой сети.

Журнал запросов на прокси:

```bash
sudo tail -f /var/log/squid/access.log
```

Имена сайтов разбирает сервер Squid. Клиенту нужен только его адрес, поэтому
в примерах указан IP, а не имя. На сервере Squid должен отвечать резолвер.
Клиенту внешний DNS для `apt` и для программ, которые ходят через этот прокси,
не требуется.

В браузере тот же адрес и порт `3128`, поле логина пустое.

### Машина без прямого интернета

Эти файлы ставят на клиенте Ubuntu 26.04, у которого наружу нет своего
маршрута. На сервере Squid их не включают: `apt` этого сервера ходит в архив
напрямую.

Одного файла на все программы нет. `apt` читает свой конфиг. Сеансы входа
читают `/etc/environment`. Службы systemd получают переменные только из
настроек менеджера.

#### apt

`apt` 3.2 в Ubuntu 26.04 берёт прокси из `/etc/apt/apt.conf.d/`. Этот файл
действует для `sudo apt-get`, для cron и для службы `unattended-upgrades`.
Пример — [`examples/client/apt.conf.d/95proxy`](../examples/client/apt.conf.d/95proxy):

```
Acquire::http::Proxy "http://192.168.0.10:3128";
Acquire::https::Proxy "http://192.168.0.10:3128";
```

В строке `https` схема тоже `http://`: apt открывает туннель `CONNECT`,
а с прокси по TLS не соединяется. Для локального зеркала, до которого клиент
ходит сам, добавьте исключение, например
`Acquire::http::Proxy::mirror.internal "DIRECT";`.

Команда из корня репозитория:

```bash
sudo install -m 644 examples/client/apt.conf.d/95proxy /etc/apt/apt.conf.d/95proxy
apt-config dump Acquire::http::Proxy Acquire::https::Proxy
sudo apt-get update
```

`apt-config` печатает оба значения с адресом прокси. `apt-get update` качает
индексы через Squid: в `access.log` появляются строки с IP клиента и именем
архива. В поставке Ubuntu 26.04 это `http://archive.ubuntu.com/ubuntu/` и
`http://security.ubuntu.com/ubuntu/`, на архитектурах кроме amd64 —
`http://ports.ubuntu.com/ubuntu-ports/`. Подпись индексов apt проверяет сам.
Репозиторий на HTTPS виден в журнале как `TCP_TUNNEL` на порт 443; сертификат
сайта проверяет клиент, для этого на нём нужны верные часы и пакет
`ca-certificates`.

#### Сеансы и sudo

Строки из [`examples/client/environment.proxy`](../examples/client/environment.proxy)
дописывают в конец `/etc/environment`. Это не скрипт: слова `export` там нет,
строку `PATH` не затирают.

```
http_proxy="http://192.168.0.10:3128"
https_proxy="http://192.168.0.10:3128"
HTTP_PROXY="http://192.168.0.10:3128"
HTTPS_PROXY="http://192.168.0.10:3128"
no_proxy="localhost,127.0.0.1,::1,192.168.0.0/16"
NO_PROXY="localhost,127.0.0.1,::1,192.168.0.0/16"
```

Оба регистра нужны: curl и wget читают `http_proxy` строчными буквами, часть
программ на Go и Java читает `HTTP_PROXY`. Запись `192.168.0.0/16` в
`no_proxy` понимает curl. wget сверяет суффикс имени, поэтому локальные имена
дописывают в тот же список отдельно.

Файл подхватывает новый вход по SSH и вход на консоли. Уже открытый сеанс
старые переменные не обновляет. `sudo` на Ubuntu читает `/etc/environment`
через `pam_env.so` в `/etc/pam.d/sudo`, поэтому `sudo curl` видит прокси сразу
после правки файла.

Проверка в новой сессии, уже без ключа `-x`:

```bash
curl -I http://example.com
curl -I https://example.com
```

#### Службы systemd

Служба не читает `/etc/environment`. Чтобы исходящие запросы служб тоже шли
через прокси, поставьте drop-in менеджера
[`examples/client/systemd/system.conf.d/60-proxy.conf`](../examples/client/systemd/system.conf.d/60-proxy.conf):

```
[Manager]
DefaultEnvironment="http_proxy=http://192.168.0.10:3128" "https_proxy=http://192.168.0.10:3128" "HTTP_PROXY=http://192.168.0.10:3128" "HTTPS_PROXY=http://192.168.0.10:3128" "no_proxy=localhost,127.0.0.1,::1,192.168.0.0/16" "NO_PROXY=localhost,127.0.0.1,::1,192.168.0.0/16"
```

```bash
sudo mkdir -p /etc/systemd/system.conf.d
sudo install -m 644 examples/client/systemd/system.conf.d/60-proxy.conf /etc/systemd/system.conf.d/60-proxy.conf
sudo systemctl daemon-reexec
```

`daemon-reexec` перечитывает `system.conf`. `daemon-reload` обновляет только
юниты. Переменную получают процессы, запущенные после этого. Уже работающую
службу перезапускают отдельно, например `sudo systemctl restart имя.service`.
Список общий для всех системных служб: локальные адреса остаются в `no_proxy`,
иначе служба пошлёт запрос к соседу в `192.168.*` на прокси.

Для одной службы достаточно своего drop-in, без общего `DefaultEnvironment`:

```bash
sudo systemctl edit имя.service
```

```
[Service]
Environment="http_proxy=http://192.168.0.10:3128" "https_proxy=http://192.168.0.10:3128" "no_proxy=localhost,127.0.0.1,::1,192.168.0.0/16"
```

Пакеты snap читают отдельные настройки snapd:

```bash
sudo snap set system proxy.http="http://192.168.0.10:3128"
sudo snap set system proxy.https="http://192.168.0.10:3128"
```

Команду пропускают, если `snapd` не установлен.

### Группа серверов через ansible-console

Те же файлы на группу клиентов Ubuntu раскладывает `ansible-console`.
В `proxy_clients` перечислите клиентские машины. Машина со Squid остаётся вне
группы: её `apt` ходит в архив напрямую.

Инвентарь, например `inventory`:

```
[proxy_clients]
192.168.0.11
192.168.0.12
```

Запуск с управляющей машины. `192.168.0.10` — адрес прокси. Если `sudo` на
клиентах спрашивает пароль, добавьте `-K`.

```bash
ansible-console proxy_clients -i inventory --become -e 'proxy=http://192.168.0.10:3128'
```

Консоль выполняет одну команду на все хосты группы. Первое слово строки — имя
модуля. Повторный запуск с другим `-e proxy=` перезаписывает уже стоящие
значения. Сначала имеет смысл посмотреть изменения без записи: `check true`.
Дальше `check false` и те же строки уже применяют настройки. `forks 20`
поднимает число параллельных хостов, по умолчанию их пять.

```
list
file path=/etc/systemd/system.conf.d state=directory mode=0755
copy dest=/etc/apt/apt.conf.d/95proxy mode=0644 content='Acquire::http::Proxy "{{ proxy }}"; Acquire::https::Proxy "{{ proxy }}";'
lineinfile path=/etc/environment regexp='^http_proxy=' line='http_proxy="{{ proxy }}"'
lineinfile path=/etc/environment regexp='^https_proxy=' line='https_proxy="{{ proxy }}"'
lineinfile path=/etc/environment regexp='^HTTP_PROXY=' line='HTTP_PROXY="{{ proxy }}"'
lineinfile path=/etc/environment regexp='^HTTPS_PROXY=' line='HTTPS_PROXY="{{ proxy }}"'
lineinfile path=/etc/environment regexp='^no_proxy=' line='no_proxy="localhost,127.0.0.1,::1,192.168.0.0/16"'
lineinfile path=/etc/environment regexp='^NO_PROXY=' line='NO_PROXY="localhost,127.0.0.1,::1,192.168.0.0/16"'
lineinfile path=/etc/systemd/system.conf.d/60-proxy.conf regexp='^\[Manager\]$' line='[Manager]' create=true mode=0644
lineinfile path=/etc/systemd/system.conf.d/60-proxy.conf regexp='^DefaultEnvironment=' line='DefaultEnvironment="http_proxy={{ proxy }}" "https_proxy={{ proxy }}" "HTTP_PROXY={{ proxy }}" "HTTPS_PROXY={{ proxy }}" "no_proxy=localhost,127.0.0.1,::1,192.168.0.0/16" "NO_PROXY=localhost,127.0.0.1,::1,192.168.0.0/16"' create=true mode=0644
systemd daemon_reexec=true
command cmd='apt-config dump Acquire::http::Proxy Acquire::https::Proxy'
apt update_cache=true
```

`lineinfile` дописывает ключи в `/etc/environment` и не трогает строку `PATH`.
`systemd daemon_reexec=true` перечитывает `system.conf` на каждом хосте группы.
Уже запущенные службы получают новые переменные после своего перезапуска.
`apt update_cache=true` качает индексы через прокси: в `access.log` Squid
видны IP клиентов.

Если на клиентах есть `snapd`, отдельно:

```
command cmd='snap set system proxy.http={{ proxy }}'
command cmd='snap set system proxy.https={{ proxy }}'
```

### Пользователь demo

В том же сеансе `ansible-console` эти строки создают на каждом хосте группы
учётную запись `demo`. Приглашение должно заканчиваться на `#`: тогда задачи
идут через `sudo`. Приглашение с `$` значит, что `become` выключен и запись в
`/etc` выполняется от имени пользователя входа. Включить:

```
become true
```

Пароль учётки закрыт: вход по паролю не проходит, вход по ключу остаётся.
`sudo` для `demo` не спрашивает пароль. Группа `sudo` на Ubuntu этого не даёт:
в ней правило с паролем. Отдельный файл `/etc/sudoers.d/demo` проверяется
через `visudo` до замены.

Ключ читается на машине, где запущена консоль, из `~/.ssh/id_ecdsa.pub`, и
дописывается в `/home/demo/.ssh/authorized_keys`. Другие строки этого файла
остаются. Если публичного ключа нет, задача останавливается и файл ключей не
меняет.

Модуль `authorized_key` в ansible-core не входит, он из коллекции
`ansible.posix`. Когда консоль такой модуль не находит, она отправляет всю
строку в удалённый `shell`, и на хосте появляется `authorized_key: not found`
с кодом 127. Каталог ключей и сам ключ поэтому пишут модули `file` и
`lineinfile` из базового набора:

```
user name=demo state=present shell=/bin/bash create_home=true password_lock=true
blockinfile path=/etc/sudoers.d/demo create=true owner=root group=root mode=0440 block='demo ALL=(ALL:ALL) NOPASSWD:ALL' validate='visudo -cf %s'
file path=/home/demo/.ssh state=directory owner=demo group=demo mode=0700
lineinfile path=/home/demo/.ssh/authorized_keys line="{{ lookup('file', '~/.ssh/id_ecdsa.pub') }}" create=true owner=demo group=demo mode=0600
```

Проверка с управляющей машины, после выхода из консоли:

```bash
ssh -i ~/.ssh/id_ecdsa demo@192.168.0.11 sudo -n true
```

`sudo -n true` завершается с кодом 0: пароль не запрашивался. Адрес замените
на хост из группы.
