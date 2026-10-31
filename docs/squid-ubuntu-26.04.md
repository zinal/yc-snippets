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

Переменные для программ, которые умеют HTTP-прокси:

```bash
export http_proxy=http://192.168.0.10:3128
export https_proxy=http://192.168.0.10:3128
export no_proxy=localhost,127.0.0.1
```

`192.168.0.10` замените на адрес прокси в сети `192.168.*`. В браузере тот же
адрес и порт `3128`, поле логина пустое.

Проверка с машины внутри `192.168.0.0/16`:

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

Журнал запросов:

```bash
sudo tail -f /var/log/squid/access.log
```
