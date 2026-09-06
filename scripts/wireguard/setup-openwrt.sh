#!/bin/bash
# Configure WireGuard on OpenWRT (Pi CM4 router).
# Run via SSH on the router after generating keys with genkeys.sh.
#
# Prerequisites:
#   opkg update && opkg install wireguard-tools luci-proto-wireguard
#
# Usage: ./setup-openwrt.sh <server-private-key> <client-public-key> [client-public-key ...]
#   Keys are passed as arguments to avoid files on the router.
#   Get them from: cat keys/server.key  and  cat keys/<client>.pub

set -euo pipefail

if [ $# -lt 2 ]; then
    echo "Usage: $0 <server-private-key> <client-public-key> [client-public-key ...]"
    echo "  First arg:  server private key (from keys/server.key)"
    echo "  Rest:       client public keys (from keys/<name>.pub)"
    exit 1
fi

SERVER_PRIVKEY="$1"
shift
CLIENT_PUBKEYS=("$@")

WG_SUBNET="10.0.0"
WG_PORT="51820"

echo "=== Configuring WireGuard interface wg0 ==="

uci set network.wg0=interface
uci set network.wg0.proto='wireguard'
uci set network.wg0.private_key="$SERVER_PRIVKEY"
uci set network.wg0.listen_port="$WG_PORT"
uci add_list network.wg0.addresses="${WG_SUBNET}.1/24"

# Add peers — each gets 10.0.0.2, 10.0.0.3, etc.
PEER_IP=2
for pubkey in "${CLIENT_PUBKEYS[@]}"; do
    echo "  Adding peer ${WG_SUBNET}.${PEER_IP} ..."
    uci add network wireguard_wg0
    uci set network.@wireguard_wg0[-1].public_key="$pubkey"
    uci set network.@wireguard_wg0[-1].allowed_ips="${WG_SUBNET}.${PEER_IP}/32"
    uci set network.@wireguard_wg0[-1].route_allowed_ips='1'
    PEER_IP=$((PEER_IP + 1))
done

echo "=== Configuring firewall ==="

# WireGuard zone
uci add firewall zone
uci set firewall.@zone[-1].name='wireguard'
uci set firewall.@zone[-1].input='ACCEPT'
uci set firewall.@zone[-1].output='ACCEPT'
uci set firewall.@zone[-1].forward='REJECT'
uci set firewall.@zone[-1].masq='1'
uci add_list firewall.@zone[-1].network='wg0'

# Allow WG → LAN forwarding
uci add firewall forwarding
uci set firewall.@forwarding[-1].src='wireguard'
uci set firewall.@forwarding[-1].dest='lan'

# Allow WireGuard UDP from WAN
uci add firewall rule
uci set firewall.@rule[-1].name='Allow-WireGuard'
uci set firewall.@rule[-1].src='wan'
uci set firewall.@rule[-1].dest_port="$WG_PORT"
uci set firewall.@rule[-1].proto='udp'
uci set firewall.@rule[-1].target='ACCEPT'

echo "=== Committing and reloading ==="

uci commit network
uci commit firewall
/etc/init.d/network reload
/etc/init.d/firewall reload

echo "Done. Verify with: wg show"
