# Flower and the Dog Toolbox — Project Plan

This document is the full context for Claude Code. It describes what we're building,
what's already done, and what still needs to happen.

---

## What we're building

A personal MCP (Model Context Protocol) server deployed on Railway, accessible from
anywhere — Claude Desktop, VS Code/Continue, and any other MCP-compatible client.

The server is called **"Flower and the Dog Toolbox"** and lives at:
- MCP server: `https://mcp.flowerandthedog.nl/sse`
- n8n: `https://n8n.flowerandthedog.nl`

Owner: Iwan van Ee

---

## Architecture

```
Claude Desktop / VS Code (Continue) / any MCP client
        │
        │  MCP over SSE (Bearer token auth)
        ▼
https://mcp.flowerandthedog.nl/sse
        │
        ▼
Railway Service: flower-and-the-dog-mcp  (this repo)
        │
        ├── tool: get_current_datetime
        ├── tool: calculate
        ├── tool: coachleo_get_plan
        ├── tool: coachleo_get_upcoming_races
        └── tool: coachleo_log_run

Railway Project: "Flower and the Dog Toolbox"
├── Service: n8n             (n8n.flowerandthedog.nl)
├── Service: mcp-server      (mcp.flowerandthedog.nl)  ← this repo
└── PostgreSQL addon         (used by n8n)
```

---

## Railway setup — already done ✅

- Railway project created: "Flower and the Dog Toolbox"
- PostgreSQL addon: online
- n8n service: online at `https://n8n-production-954c.up.railway.app`
  - Docker image: `n8nio/n8n:latest`
  - Volume: `/home/node/.n8n`
  - Custom domain `n8n.flowerandthedog.nl` added (DNS propagating)
  - All env vars set including DB connection via `${{Postgres.*}}` references

## DNS — already done ✅

At YourHosting (Plesk) for `flowerandthedog.nl`:
- CNAME `n8n` → `capivvc2.up.railway.app`
- TXT `_railway-verify.n8n` → `railway-verify=...` (verification record)

Still to add (for MCP server, after Railway service is created):
- CNAME `mcp` → `<railway-mcp-service-url>.up.railway.app`
- TXT `_railway-verify.mcp` → `railway-verify=...`

---

## This repo — current state

```
flower-and-the-dog-mcp/
├── PLAN.md              ← this file
├── README.md
├── server.py            ← main MCP server (Starlette + SSE transport)
├── requirements.txt
├── railway.toml
└── tools/
    ├── __init__.py
    └── coachleo.py      ← Coach Leo integration (placeholder, ready to wire up)
```

### server.py

- Starlette app with SSE transport (`/sse` endpoint)
- Bearer token auth middleware (reads `MCP_SECRET_TOKEN` env var)
- `/health` endpoint for Railway healthcheck
- Tools registered: `get_current_datetime`, `calculate`, `coachleo_get_plan`,
  `coachleo_get_upcoming_races`, `coachleo_log_run`

### tools/coachleo.py

- All three functions are placeholders returning `{"status": "placeholder", ...}`
- Ready to wire up once Coach Leo exposes API endpoints
- Reads `COACHLEO_BASE_URL` and `COACHLEO_API_KEY` from environment

---

## Next steps

### Step 1 — Deploy MCP server to Railway ✅

1. In Railway → "Flower and the Dog Toolbox" project → Add Service → GitHub Repo
2. Select `flower-and-the-dog-mcp`
3. Add environment variables:
   ```
   MCP_SECRET_TOKEN    →  generate with: openssl rand -hex 32
   COACHLEO_BASE_URL   →  https://coachleo.up.railway.app  (fill in later)
   COACHLEO_API_KEY    →  (fill in later)
   ```
4. Railway auto-deploys from `railway.toml`

### Step 2 — Add custom domain for MCP server ⏳ (DNS propagating)

1. Railway → mcp service → Settings → Networking → Add Custom Domain → `mcp.flowerandthedog.nl`
2. Railway shows required DNS records (CNAME + TXT verify)
3. Add both records in YourHosting DNS panel
4. Wait for propagation (usually fast)

### Step 3 — Test MCP server

```bash
# Health check
curl https://mcp.flowerandthedog.nl/health

# Test SSE connection (should get 401 without token)
curl https://mcp.flowerandthedog.nl/sse

# Test with token
curl https://mcp.flowerandthedog.nl/sse \
  -H "Authorization: Bearer YOUR_MCP_SECRET_TOKEN"
```

### Step 4 — Configure Claude Desktop ✅ (klaar, wacht op DNS)

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "flower-and-the-dog": {
      "type": "sse",
      "url": "https://mcp.flowerandthedog.nl/sse",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_SECRET_TOKEN"
      }
    }
  }
}
```

Restart Claude Desktop. The tools should appear.

### Step 5 — Configure VS Code / Continue

Edit `.continue/config.json`:

```json
{
  "mcpServers": [
    {
      "name": "flower-and-the-dog",
      "transport": {
        "type": "sse",
        "url": "https://mcp.flowerandthedog.nl/sse",
        "requestInit": {
          "headers": {
            "Authorization": "Bearer YOUR_MCP_SECRET_TOKEN"
          }
        }
      }
    }
  ]
}
```

### Step 6 — Wire up Coach Leo

When Coach Leo (NestJS on Railway) exposes API endpoints:

1. Update `tools/coachleo.py` — uncomment the actual HTTP calls and set correct endpoint paths
2. Set `COACHLEO_BASE_URL` and `COACHLEO_API_KEY` in Railway MCP service variables
3. Redeploy

Coach Leo is an Angular 19 + NestJS + PostgreSQL personal training app for distance
runners (Strava integration, AI-generated plans with 10% rule, cutback weeks, race tapers).
Deployed on Railway.

### Step 7 — Add carwash tool ✅

- `tools/carwash.py` aangemaakt (async, httpx, Excel parser)
- Geregistreerd in `server.py`
- `CARWASH_USERNAME` + `CARWASH_PASSWORD` staan in Railway env vars

---

## Adding new tools (general pattern)

1. Create `tools/mytool.py` with async functions
2. Import in `server.py`
3. Add `Tool(name="...", description="...", inputSchema={...})` to `list_tools()`
4. Add handler in `call_tool()` elif block
5. Push → Railway auto-redeploys

---

## Environment variables reference

| Variable | Where | Description |
|----------|-------|-------------|
| `MCP_SECRET_TOKEN` | MCP service | Bearer token for all clients |
| `COACHLEO_BASE_URL` | MCP service | Base URL of Coach Leo API |
| `COACHLEO_API_KEY` | MCP service | Coach Leo JWT/API key |
| `PORT` | MCP service | Set by Railway automatically |
| `N8N_ENCRYPTION_KEY` | n8n service | Encrypts stored credentials |
| `WEBHOOK_URL` | n8n service | `https://n8n.flowerandthedog.nl` |
| `DB_TYPE` + `DB_POSTGRESDB_*` | n8n service | PostgreSQL connection via Railway refs |

---

## Useful URLs

| What | URL |
|------|-----|
| n8n UI | https://n8n.flowerandthedog.nl |
| MCP SSE endpoint | https://mcp.flowerandthedog.nl/sse |
| MCP health | https://mcp.flowerandthedog.nl/health |
| Railway project | https://railway.app (project: Flower and the Dog Toolbox) |
| GitHub repo | https://github.com/icvanee/flower-and-the-dog-mcp |
