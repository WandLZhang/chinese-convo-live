#!/bin/bash
# One-time: link this VM as a Signal device. Shows a QR in the terminal; scan it in
# Signal on your phone (Settings -> Linked Devices -> + Link New Device). Run as root:
#   sudo /opt/signal_link.sh
set -e
tmp=$(mktemp)
signal-cli link -n "convo-live-signal" > "$tmp" 2>/dev/null &
pid=$!
for _ in $(seq 1 40); do [ -s "$tmp" ] && break; sleep 0.5; done
uri=$(head -1 "$tmp")
if [ -z "$uri" ]; then echo "Failed to get linking URI."; kill "$pid" 2>/dev/null || true; exit 1; fi
echo
echo "Signal on phone -> Settings -> Linked Devices -> + (Link New Device) -> scan this QR:"
echo
echo "$uri" | qrencode -t UTF8
echo
echo "Waiting for you to scan + approve (finishes automatically)..."
wait "$pid"
echo
echo "LINKED. Account(s):"
signal-cli listAccounts
