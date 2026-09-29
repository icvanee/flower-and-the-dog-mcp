# Flower and the Dog — MCP Toolbox

Persoonlijke MCP-server van Iwan. Draait op de Mac Mini (launchd-agent `nl.icvanee.mcp`
uit mac-mini-setup) op `127.0.0.1:8765` en is publiek bereikbaar via Tailscale Funnel
op `https://<mini>.<tailnet>.ts.net`. Te koppelen als custom connector in claude.ai (ook
op iPhone), met OAuth in plaats van een vaste Bearer-token.

- Transport: Streamable HTTP op `/mcp`
- Health check: `/health`
- OAuth 2.1 met PKCE en dynamic client registration, via de autorisatieserver van de MCP
  SDK. Er is één gebruiker: bij het koppelen toont `/login` een wachtwoordpagina
  (`MCP_LOGIN_PASSWORD`). Tokens staan gehasht in `~/.local/share/flower-and-the-dog-mcp/oauth.sqlite`.

## Tools

| Tool | Wat |
|------|-----|
| `get_current_datetime` | Datum, weekdag en tijd in Nederland |
| `carwash_get_history` | Wasgeschiedenis bij Carwash Kleiboer |
| `recente_trainingen` | Laatste trainingen (standaard hardlopen) |
| `training_details` | Eén training: zones, splits, schema, notities |
| `notitie_bij_training` | Vult de notities van een training aan (nooit overschrijven) |
| `status_notitie` | Notitie los van een training, bijv. over de heup |
| `status_notities` | Recente statusnotities |
| `trainingsschema` | Wat er de komende dagen gepland staat |

De trainingstools lezen en schrijven de Postgres van health-dashboard als rol `mcp`
(`HEALTH_DATABASE_URL`). Die rol mag lezen uit `Run`, `RunSplit`, `StatusNote` en
`TrainingPlanEntry`, alleen `Run.notes`/`updatedAt` wijzigen en `StatusNote` aanvullen:

```sql
CREATE ROLE mcp LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE health TO mcp;
GRANT USAGE ON SCHEMA public TO mcp;
GRANT SELECT ON "Run", "RunSplit", "StatusNote", "TrainingPlanEntry" TO mcp;
GRANT UPDATE (notes, "updatedAt") ON "Run" TO mcp;
GRANT INSERT ON "StatusNote" TO mcp;
GRANT USAGE ON SEQUENCE "StatusNote_id_seq" TO mcp;
```

## Draaien

```bash
uv sync
mkdir -p ~/.config/flower-and-the-dog-mcp
cp env.example ~/.config/flower-and-the-dog-mcp/env && chmod 600 ~/.config/flower-and-the-dog-mcp/env
./run.sh
```

Op de Mini start launchd `run.sh` (`./install-agents.sh mcp` in mac-mini-setup) en maakt
`sudo tailscale funnel --bg 8765` de server publiek.

## Configuratie

| Variabele | Standaard | Wat |
|-----------|-----------|-----|
| `MCP_PUBLIC_URL` | `http://localhost:8765` | Publieke basis-URL; wordt de OAuth-issuer |
| `MCP_PORT` | `8765` | Lokale poort |
| `MCP_HOST` | `127.0.0.1` | Bind-adres |
| `MCP_LOGIN_PASSWORD` | — (verplicht) | Wachtwoord op de inlogpagina |
| `MCP_DATA_DIR` | `~/.local/share/flower-and-the-dog-mcp` | Plek van `oauth.sqlite` |
| `MCP_ALLOWED_REDIRECT_HOSTS` | `claude.ai,claude.com,localhost,127.0.0.1` | Toegestane OAuth-redirects |
| `CARWASH_USERNAME`, `CARWASH_PASSWORD` | — | Carwash-portaal |
| `HEALTH_DATABASE_URL` | — | Postgres van health-dashboard, als rol `mcp` (poort 5433) |

## Koppelen

claude.ai → Settings → Connectors → Add custom connector → `https://<mini>.<tailnet>.ts.net/mcp`.
Claude opent de inlogpagina; vul het wachtwoord in. De connector werkt daarna ook in de
iPhone-app.

Alle koppelingen intrekken: stop de server en verwijder `oauth.sqlite`.
