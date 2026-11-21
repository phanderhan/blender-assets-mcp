#!/bin/sh
set -eu

# The server starts only after this container becomes healthy. Fail closed while
# configuring both families, including when a subsequent command fails.
iptables -P OUTPUT DROP
iptables -P INPUT DROP
iptables -P FORWARD DROP
ip6tables -P OUTPUT DROP
ip6tables -P INPUT DROP
ip6tables -P FORWARD DROP

iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
# Docker's embedded resolver uses DNAT to a dynamically allocated port. Match
# the original destination port so other loopback services remain inaccessible.
iptables -A INPUT -d 127.0.0.11 -p udp -m conntrack --ctorigdstport 53 -j ACCEPT
iptables -A INPUT -d 127.0.0.11 -p tcp -m conntrack --ctorigdstport 53 -j ACCEPT
iptables -A OUTPUT -s 127.0.0.11 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -d 127.0.0.11 -p udp -m conntrack --ctorigdstport 53 -j ACCEPT
iptables -A OUTPUT -d 127.0.0.11 -p tcp -m conntrack --ctorigdstport 53 -j ACCEPT

for net in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 \
    172.16.0.0/12 192.0.0.0/24 192.0.2.0/24 192.88.99.0/24 192.168.0.0/16 \
    198.18.0.0/15 198.51.100.0/24 203.0.113.0/24 224.0.0.0/4 240.0.0.0/4; do
    iptables -A OUTPUT -d "$net" -j DROP
done
iptables -A OUTPUT -p tcp --dport 443 -j ACCEPT

# The namespace and firewall must stay alive for the server's lifetime.
exec sleep infinity
