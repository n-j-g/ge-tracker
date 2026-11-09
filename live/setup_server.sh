#!/bin/bash
# One-time setup for the transfer-trap paper trader on a fresh Ubuntu server.
#
# Paste this whole file into the "initialization script" / "user data" box when you
# create the server (see live/README.md). Before pasting, replace PASTE_TOKEN_HERE
# below with your GitHub token for the ge-paper-data repository. Nothing else to edit.
#
# What it does: installs git and Python, downloads ge-tracker from GitHub, and runs
# live/watch.py as a background service that restarts itself if it stops. Once an hour
# it picks up any code changes pushed to GitHub, so updates need no login.

TOKEN="PASTE_TOKEN_HERE"
DATA_REPO="n-j-g/ge-paper-data"
CODE_REPO="https://github.com/n-j-g/ge-tracker.git"

set -eux
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git python3

# 1 GB of swap so a small server never runs out of memory.
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

id ge >/dev/null 2>&1 || useradd -m -s /bin/bash ge
[ -d /home/ge/ge-tracker ] || sudo -u ge git clone -q "$CODE_REPO" /home/ge/ge-tracker

# Settings (the token stays on this server, readable only by root and the service).
install -m 640 -o root -g ge /dev/null /etc/ge-paper.env
cat > /etc/ge-paper.env <<EOF
PAPER_PUSH_URL=https://bot:${TOKEN}@github.com/${DATA_REPO}.git
GE_PROFIT_USER_AGENT=ge-tracker paper-trader (+https://github.com/n-j-g/ge-tracker)
EOF

cat > /etc/systemd/system/ge-paper.service <<'EOF'
[Unit]
Description=GE transfer-trap paper trading
After=network-online.target
Wants=network-online.target

[Service]
User=ge
WorkingDirectory=/home/ge/ge-tracker
EnvironmentFile=/etc/ge-paper.env
ExecStart=/usr/bin/python3 -m live.watch --data /home/ge/paper-data
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

cat > /usr/local/bin/ge-paper-update <<'EOF'
#!/bin/bash
# Pull code changes from GitHub; restart the watcher if anything changed.
cd /home/ge/ge-tracker || exit 0
old=$(sudo -u ge git rev-parse HEAD)
sudo -u ge git pull -q --ff-only || exit 0
new=$(sudo -u ge git rev-parse HEAD)
if [ "$old" != "$new" ]; then systemctl restart ge-paper; fi
EOF
chmod 755 /usr/local/bin/ge-paper-update

cat > /etc/systemd/system/ge-paper-update.service <<'EOF'
[Unit]
Description=Update the GE paper trader from GitHub

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ge-paper-update
EOF

cat > /etc/systemd/system/ge-paper-update.timer <<'EOF'
[Unit]
Description=Check GitHub for paper-trader updates every hour

[Timer]
OnBootSec=15min
OnUnitActiveSec=1h
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now ge-paper.service ge-paper-update.timer
