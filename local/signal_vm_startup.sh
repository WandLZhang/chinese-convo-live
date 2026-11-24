#!/bin/bash
# Startup script for the convo-live-signal VM: installs Java 21 + signal-cli + a Python venv with
# the deps the ingestion script needs. Interactive `signal-cli link` (QR) and the ingestion
# script + cron are set up over IAP SSH afterward. Logs to /var/log/convo-signal-setup.log.
exec > /var/log/convo-signal-setup.log 2>&1
set -ex
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y curl jq python3 python3-venv wget apt-transport-https gpg qrencode
# Temurin 25 JRE (signal-cli 0.14.6 needs Java 25; Debian 12 has no openjdk-21/25 candidate)
mkdir -p /etc/apt/keyrings
wget -qO- https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor -o /etc/apt/keyrings/adoptium.gpg
echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb bookworm main" > /etc/apt/sources.list.d/adoptium.list
apt-get update
apt-get install -y temurin-25-jre

# signal-cli, pinned. This script runs at every boot as root on the box that holds the Signal keys, so
# a reboot must never pull an unreviewed release. Bump VER by hand after reading the release notes.
VER=0.14.6
echo "signal-cli version: $VER"
if [ ! -x "/opt/signal-cli-${VER}/bin/signal-cli" ]; then
  cd /opt
  curl -fsSL -o signal-cli.tar.gz "https://github.com/AsamK/signal-cli/releases/download/v${VER}/signal-cli-${VER}.tar.gz"
  tar xf signal-cli.tar.gz
fi
ln -sf "/opt/signal-cli-${VER}/bin/signal-cli" /usr/local/bin/signal-cli

# The ingest log holds the messages it read, so it keeps 30 days, like the Firestore entries.
cat > /etc/logrotate.d/signal-ingest <<'ROT'
/var/log/signal-ingest.log {
    daily
    rotate 30
    maxage 30
    missingok
    notifempty
    compress
    delaycompress
    create 0600 root root
}
ROT
chmod 600 /var/log/signal-ingest.log 2>/dev/null || true

# python venv for the ingestion script
[ -x /opt/venv/bin/python ] || python3 -m venv /opt/venv
/opt/venv/bin/pip install -q --upgrade pip
/opt/venv/bin/pip install -q google-cloud-firestore requests google-auth

# sanity
java -version
signal-cli --version || echo "SIGNAL-CLI CHECK FAILED"
touch /var/log/convo-signal-setup-DONE
echo "SETUP COMPLETE"
