# Deploying Stockify to Render (Free Tier)

End state: `https://stockify.onrender.com` (or whatever name you pick) serves
the app with real HTTPS. Zero ongoing cost. One service to manage.

Rough time: 10 minutes.

## Tradeoffs to accept on free tier

- **Sleeps after 15 min idle.** First request after sleep adds ~30s spin-up,
  *then* 60s for brief generation. Painful for live demos; fine for a portfolio link.
- **No persistent disk.** SQLite gets wiped on every redeploy or sleep. You
  have two choices:
  - **(a) Ephemeral SQLite** — users can sign up and use the app, but accounts
    and watchlists are lost on every redeploy. Fine for a "click around and try
    it" demo.
  - **(b) Free Postgres via Neon** — accounts persist across redeploys. ~3 extra
    minutes of setup. **Recommended.**

## 1. Push your repo to GitHub

Render deploys from a GitHub repo. If you haven't already:

```bash
gh repo create stockify --public --source=. --push
```

## 2. Optional — create free Postgres on Neon

Skip this section if you're fine with ephemeral SQLite.

1. Sign up at https://neon.tech (GitHub login, no credit card)
2. Create a new project (pick the region nearest your Render region)
3. Copy the connection string — it looks like:
   ```
   postgresql://user:pw@ep-foo-123.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
4. Rewrite the prefix for SQLAlchemy's async-capable psycopg3 driver:
   ```
   postgresql+psycopg://user:pw@ep-foo-123.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
5. Add the Postgres driver to the project (Render won't have it otherwise):
   ```bash
   uv add "psycopg[binary]>=3.1"
   git commit -am "deps: add psycopg for postgres" && git push
   ```

## 3. Deploy to Render

1. Sign in at https://render.com (GitHub login, no credit card)
2. Click **New → Blueprint**
3. Connect your GitHub account, select the `stockify` repo
4. Render reads `render.yaml` and shows the plan. Click **Apply**
5. In the service settings, set these secrets in the **Environment** tab:
   - `GEMINI_API_KEY` — your Google Gemini key
   - `DATABASE_URL` — the Neon string from step 2 (or leave blank for SQLite)
6. Render builds the Docker image and starts the service (~3–5 min first build)

Your URL will be `https://stockify.onrender.com` (or `stockify-<suffix>` if
the name was taken). HTTPS is automatic.

## 4. Verify

```bash
curl https://<your-name>.onrender.com/health
# {"status":"ok","version":"0.2.0",...}
```

Open the URL in a browser and sign up.

## Updating later

Just push to `main` — Render auto-deploys from GitHub. Builds take 3–5 minutes.

## Waking it up

If the service has been idle for 15 min it sleeps. Any HTTP request wakes it
(~30s). A cheap trick to keep it warm: set up a free cron-job.org monitor hitting
`/health` every 10 minutes. Don't do this if you're fine with it sleeping —
you'll burn through your 750 free hours/month otherwise.

## Troubleshooting

**Build fails with "out of memory".** Free tier has 512 MB during build. The
`scripts/build_knowledge_graph.py` step in the Dockerfile is the usual culprit —
it downloads the S&P 500 list. If it OOMs, commit the pre-built
`src/knowledge_graph/data/sp500_graph.json` to the repo (it already is) and
change `RUN uv run python scripts/build_knowledge_graph.py || true` in the
Dockerfile to just `echo "skip — using committed graph"`.

**App returns 500 on `/brief`.** Check `GEMINI_API_KEY` is set in Render's
Environment tab. Logs: Render dashboard → service → Logs.

**Postgres connection fails.** Make sure the URL starts with
`postgresql+psycopg://` not `postgresql://`, and that `psycopg[binary]` is in
`pyproject.toml`.
