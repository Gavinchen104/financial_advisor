# Deploying Stockify to Oracle Cloud (Always Free)

End state: `https://<your-ip>.nip.io` serves the app, TLS is real (Let's Encrypt),
SQLite persists across reboots, zero ongoing cost, no sleep.

Rough time: 30–40 minutes, most of it waiting for Oracle.

## 1. Create an Oracle Cloud account

Go to https://signup.cloud.oracle.com and create an **Always Free** account.
Credit card required for identity verification but you won't be charged. Pick a
region geographically close to you — it's locked in for the account.

## 2. Provision the VM

In the Oracle Cloud console:

1. **Compute → Instances → Create Instance**
2. **Image:** Canonical Ubuntu 22.04 or 24.04 (**Minimal** is fine)
3. **Shape:** click *Change shape* → **Ampere (Arm)** → `VM.Standard.A1.Flex`
   - 4 OCPU, 24 GB RAM (the whole Always-Free ARM allotment — take it all)
4. **Networking:** keep defaults, **check "Assign a public IPv4 address"**
5. **SSH keys:** upload your `~/.ssh/id_ed25519.pub` (or generate one in the console and save the private key)
6. **Create**

Wait until the status is **Running**. Note the **Public IP address**.

## 3. Open the firewall (Oracle-side)

Oracle blocks inbound traffic at the virtual cloud network (VCN) level by default.

1. **Networking → Virtual Cloud Networks → <your VCN> → <default subnet> → Default Security List**
2. Add two **Ingress Rules**:
   - Source `0.0.0.0/0`, protocol TCP, destination port **80**
   - Source `0.0.0.0/0`, protocol TCP, destination port **443**

(Port 22 is already open for SSH.)

## 4. SSH in and run the bootstrap

```bash
ssh ubuntu@<your-public-ip>

# One-liner bootstrap. Replace the URL with your fork if you've forked.
curl -fsSL https://raw.githubusercontent.com/<your-user>/financial_advisor/main/deploy/setup.sh | bash
```

First run does three things then exits:
- Installs Docker + opens the OS firewall
- Clones the repo into `~/financial_advisor`
- Creates `.env` with a generated `SECRET_KEY` and auto-detected `DOMAIN=<ip>.nip.io`

Then edit the `.env` to paste your Gemini key:
```bash
cd ~/financial_advisor
nano .env        # set GEMINI_API_KEY=...
bash deploy/setup.sh     # re-run; this time it boots the app
```

## 5. Verify

Wait ~30 seconds for Caddy to fetch a TLS cert, then:

```bash
curl https://<your-ip>.nip.io/health
# {"status":"ok",...}
```

Open `https://<your-ip>.nip.io` in a browser.

## Updating later

```bash
ssh ubuntu@<your-public-ip>
cd ~/financial_advisor
git pull
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
```

Or just re-run `bash deploy/setup.sh` — it's idempotent.

## Optional: use your own domain

1. In your DNS provider, create an **A record** for `app.yourdomain.com` → `<your-ip>`
2. Edit `~/financial_advisor/.env` on the VM, change `DOMAIN=app.yourdomain.com`
3. Restart: `docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d`

Caddy will fetch a fresh cert for the new domain on the next request.

## Troubleshooting

**Caddy can't get a cert.** Usually means port 80 isn't reachable from the
public internet. Check Oracle's security list (step 3) and `sudo ufw status`.

**App is up but `/brief` returns 500.** Check `GEMINI_API_KEY` is set:
```bash
docker compose exec app env | grep GEMINI
```

**SQLite looks empty after a redeploy.** Make sure the `./data` bind-mount
didn't get wiped. Your DB lives at `~/financial_advisor/data/app.db`.

**Memory spikes.** The A1 has 24 GB — you're fine. But if you ever see OOM
kills, the usual suspect is yfinance downloading too many histories in
parallel. Lower `max_workers` in `src/tools/context.py` and `src/agent.py`.
