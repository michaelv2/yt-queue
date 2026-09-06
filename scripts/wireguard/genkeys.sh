#!/bin/bash
# Generate WireGuard key pairs for server + N clients.
# Run on the OpenWRT router (or any machine with wg installed).
#
# Usage: ./genkeys.sh [client_name ...]
#   e.g. ./genkeys.sh phone laptop tablet
#
# Output: keys/ directory with .key (private) and .pub (public) files.

set -euo pipefail

OUTDIR="$(dirname "$0")/keys"
mkdir -p "$OUTDIR"
chmod 700 "$OUTDIR"

gen_pair() {
    local name="$1"
    wg genkey | tee "$OUTDIR/${name}.key" | wg pubkey > "$OUTDIR/${name}.pub"
    chmod 600 "$OUTDIR/${name}.key"
    echo "  $name: $(cat "$OUTDIR/${name}.pub")"
}

echo "Generating server key pair..."
gen_pair server

CLIENTS=("${@:-phone}")
echo "Generating client key pairs..."
for client in "${CLIENTS[@]}"; do
    gen_pair "$client"
done

echo ""
echo "Keys written to $OUTDIR/"
echo "IMPORTANT: Keep .key files secret. Never commit them to git."
