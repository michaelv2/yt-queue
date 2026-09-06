#!/bin/bash
# DuckDNS update script for OpenWRT.
# Install as a cron job on the router:
#
#   crontab -e
#   */5 * * * * /root/ddns-cron.sh
#
# Or use luci-app-ddns for a GUI-based setup.
#
# Set your token and domain below.

DUCKDNS_TOKEN="YOUR-TOKEN-HERE"
DUCKDNS_DOMAIN="YOUR-SUBDOMAIN"

curl -s "https://www.duckdns.org/update?domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip=" \
    -o /dev/null
