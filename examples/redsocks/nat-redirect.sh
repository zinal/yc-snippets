#!/bin/sh
# Клиент: исходящие TCP/80 и TCP/443 уходят в локальный redsocks.
# Запускать после установки пакета redsocks: ему нужен пользователь redsocks.
# На сервере Squid не запускать.

set -eu

iptables -t nat -N REDSOCKS 2>/dev/null || true
iptables -t nat -F REDSOCKS

for net in \
	0.0.0.0/8 \
	10.0.0.0/8 \
	100.64.0.0/10 \
	127.0.0.0/8 \
	169.254.0.0/16 \
	172.16.0.0/12 \
	192.168.0.0/16 \
	198.18.0.0/15 \
	224.0.0.0/4 \
	240.0.0.0/4
do
	iptables -t nat -A REDSOCKS -d "$net" -j RETURN
done

iptables -t nat -A REDSOCKS -p tcp --dport 80 -j REDIRECT --to-ports 12345
iptables -t nat -A REDSOCKS -p tcp --dport 443 -j REDIRECT --to-ports 12346

if ! iptables -t nat -C OUTPUT -p tcp -m owner --uid-owner redsocks -j RETURN 2>/dev/null; then
	iptables -t nat -I OUTPUT 1 -p tcp -m owner --uid-owner redsocks -j RETURN
fi

if ! iptables -t nat -C OUTPUT -p tcp -m multiport --dports 80,443 -j REDSOCKS 2>/dev/null; then
	iptables -t nat -A OUTPUT -p tcp -m multiport --dports 80,443 -j REDSOCKS
fi
