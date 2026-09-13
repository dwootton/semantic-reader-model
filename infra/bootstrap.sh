#!/usr/bin/env bash
set -euo pipefail
exec >> /var/log/semantic-reader-bootstrap.log 2>&1
export DEBIAN_FRONTEND=noninteractive
date -Is
apt-get update
apt-get install -y python3-venv python3-pip docker.io git curl jq
systemctl enable --now docker
mkdir -p /opt/semantic-reader
python3 -m venv /opt/semantic-reader/venv
/opt/semantic-reader/venv/bin/pip install --upgrade pip
docker pull am1n3e/webarena-verified-shopping_admin:latest
docker inspect --format='{{index .RepoDigests 0}}' am1n3e/webarena-verified-shopping_admin:latest > /opt/semantic-reader/benchmark-image-digest.txt
docker run -d --name webarena-verified-shopping_admin --restart unless-stopped -p 127.0.0.1:7780:80 -p 127.0.0.1:7781:8877 "$(cat /opt/semantic-reader/benchmark-image-digest.txt)"
touch /opt/semantic-reader/bootstrap-ready
date -Is
