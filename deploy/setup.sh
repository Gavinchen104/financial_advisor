#!/usr/bin/env bash
# One-time server bootstrap for Oracle Cloud Always Free (Ubuntu 22.04/24.04 ARM).
# Idempotent — safe to re-run.
#
# Usage:
#   ssh ubuntu@<vm-ip>
#   curl -fsSL https://raw.githubusercontent.com/<you>/financial_advisor/main/deploy/setup.sh | bash
#
# Or after cloning locally:
#   cd financial_advisor && bash deploy/setup.sh

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/gavin/financial_advisor.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/financial_advisor}"

say() { printf "\033[1;36m==>\033[0m %s\n" "$*"; }

# --- Docker ---
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker"
  sudo apt-get update -y
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  sudo usermod -aG docker "$USER"
  say "Docker installed. You may need to log out + back in for group changes."
else
  say "Docker already installed."
fi

# --- Firewall ---
if ! command -v ufw >/dev/null 2>&1; then
  sudo apt-get install -y ufw
fi
say "Opening firewall (22, 80, 443)"
sudo ufw allow 22/tcp  >/dev/null
sudo ufw allow 80/tcp  >/dev/null
sudo ufw allow 443/tcp >/dev/null
sudo ufw --force enable >/dev/null || true

# Oracle VMs also block at the iptables level by default. Open there too.
if sudo iptables -L INPUT -n | grep -q "REJECT.*reject-with icmp-host-prohibited"; then
  say "Patching iptables (Oracle's default block rule)"
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80  -j ACCEPT
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
  sudo netfilter-persistent save 2>/dev/null || sudo bash -c "iptables-save > /etc/iptables/rules.v4" 2>/dev/null || true
fi

# --- Repo ---
if [ ! -d "$INSTALL_DIR/.git" ]; then
  say "Cloning repo → $INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
else
  say "Pulling latest"
  git -C "$INSTALL_DIR" pull --ff-only
fi

cd "$INSTALL_DIR"

# --- .env ---
if [ ! -f .env ]; then
  say "Creating .env — you'll need to fill in secrets next"
  cp .env.example .env

  # Auto-detect public IP and default DOMAIN to a nip.io hostname
  PUBLIC_IP=$(curl -fsS https://api.ipify.org || echo "")
  if [ -n "$PUBLIC_IP" ]; then
    NIP_DOMAIN=$(echo "$PUBLIC_IP" | tr '.' '-').nip.io
    echo "DOMAIN=$NIP_DOMAIN" >> .env
    say "DOMAIN set to $NIP_DOMAIN"
  fi

  # Auto-generate a SECRET_KEY
  SECRET=$(openssl rand -hex 32)
  sed -i "s|SECRET_KEY=.*|SECRET_KEY=$SECRET|" .env
  say "Generated SECRET_KEY"

  say "EDIT .env now and set GEMINI_API_KEY, then re-run: bash deploy/setup.sh"
  exit 0
fi

if ! grep -q "^GEMINI_API_KEY=.\+" .env; then
  say "GEMINI_API_KEY is empty in .env. Edit it, then re-run."
  exit 1
fi

# --- Launch ---
say "Building and starting containers"
# Use sudo in case user hasn't re-logged-in for docker group yet
DOCKER="docker"
if ! docker ps >/dev/null 2>&1; then DOCKER="sudo docker"; fi

$DOCKER compose -f docker-compose.yml -f deploy/docker-compose.prod.yml pull || true
$DOCKER compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build

say "Deployed. Wait ~30s for Caddy to fetch a TLS cert, then visit:"
grep '^DOMAIN=' .env | sed 's/^DOMAIN=/  https:\/\//'
