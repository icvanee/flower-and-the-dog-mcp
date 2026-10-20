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
| `recente_trainingen` | Laatste trainingen (standaard hardlopen), met cadans |
| `training_details` | Eén training: zones, cadans en staplengte, splits, schema, notities |
| `notitie_bij_training` | Vult de notities van een training aan (nooit overschrijven) |
| `status_notitie` | Notitie los van een training, bijv. over de heup |
| `status_notities` | Recente statusnotities |
| `trainingsschema` | Wat er de komende dagen gepland staat |
| `cadans_trend` | Cadans per week of maand, met staplengte, tempo, hartslag; rustige vs. snelle runs |
| `agenda` | Afspraken voor een dag of periode (max. 14 dagen) uit iCloud en de werkagenda |
| `afspraak_plannen` | Nieuwe afspraak in iCloud; eerst voorlezen, pas na "ja" opslaan (`bevestigd`) |
| `mijn_dag` | Dagbriefing: eerste afspraak, training, rest van de dag, herinneringen die vervallen of over tijd zijn |
| `scenes` | HomeKit-scènes die de connector kan aanzetten |
| `scene` | Zet een scène aan, na bevestiging; alleen opdrachten die met "Scene " beginnen |
| `herinnering_maken` | Nieuwe herinnering in Apple Herinneringen (standaard lijst "Herinneringen"), ook met `bevestigd` |

De trainingstools lezen en schrijven de Postgres van health-dashboard als rol `mcp`
(`HEALTH_DATABASE_URL`). Die rol mag lezen uit `Run`, `RunSplit`, `StatusNote` en
`TrainingPlanEntry` (en `RunSample`, voor de cadans per km), alleen `Run.notes`/`updatedAt`
wijzigen en `StatusNote` aanvullen:

```sql
CREATE ROLE mcp LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE health TO mcp;
GRANT USAGE ON SCHEMA public TO mcp;
GRANT SELECT ON "Run", "RunSplit", "StatusNote", "TrainingPlanEntry", "RunSample" TO mcp;
GRANT UPDATE (notes, "updatedAt") ON "Run" TO mcp;
GRANT INSERT ON "StatusNote" TO mcp;
GRANT USAGE ON SEQUENCE "StatusNote_id_seq" TO mcp;
```

De agendatools praten via CalDAV met iCloud (`caldav.icloud.com`), niet via de Agenda-app,
zodat de Mini geen toegang tot Agenda hoeft te krijgen. Ze kunnen lezen en toevoegen, niet
verwijderen of verplaatsen.

Herinneringen staan niet in CalDAV, dus `herinnering_maken` gaat via de Herinneringen-app op
de Mini (AppleScript). De eerste aanroep vanuit launchd vraagt op het scherm van de Mini om
toestemming (Automatisering → Herinneringen); die moet één keer worden goedgekeurd.
`mijn_dag` leest de open herinneringen uit een cache die de server elke 10 minuten op de
achtergrond ververst: de Herinneringen-app doet tientallen seconden over lijsten met veel
afgevinkte herinneringen. De werkagenda komt uit een ICS-feed (`tools/werkagenda.py`); extra bronnen komen in
`AFSPRAAK_BRONNEN` in `tools/dag.py`.

HomeKit-scènes lopen via Opdrachten op de Mini (`shortcuts run`). Alleen opdrachten waarvan
de naam met "Scene " begint, kunnen worden uitgevoerd; maak voor een nieuwe scène een
opdracht "Scene <naam>" die de HomeKit-scène aanzet.

## Draaien

```bash
uv sync
mkdir -p ~/.config/flower-and-the-dog-mcp
cp env.example ~/.config/flower-and-the-dog-mcp/env && chmod 600 ~/.config/flower-and-the-dog-mcp/env
./run.sh
```

Op de Mini start launchd `run.sh` (`./install-agents.sh mcp` in mac-mini-setup) en maakt
`sudo tailscale funnel --bg 8765` de server publiek.

De secrets staan in de 1Password-kluis "Mac Mini"; het env-bestand bevat alleen
`op://`-verwijzingen. `run.sh` lost die op met `op run` en het alleen-lezen-token uit de
Keychain (`op-sa-macmini`, zie het hoofdstuk 1Password in mac-mini-setup). Platte waarden
omzetten: `scripts/env-to-op.sh`.

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
| `ICLOUD_CALDAV_USERNAME`, `ICLOUD_CALDAV_PASSWORD` | — | Apple ID en app-specifiek wachtwoord voor iCloud CalDAV |
| `AGENDA_CALENDARS` | `home,Family,Coach Leo` | Agenda's die `agenda` leest |
| `AGENDA_EXTRA_CALENDARS` | `Verjaardagen,Feestdagen` | Extra bij `ook_verjaardagen` |
| `WORK_CALENDAR_ICS_URL` | — | Gepubliceerde Outlook-ICS-feed van de werkagenda (alleen lezen, 15 min gecachet). Bevat een geheim token: nooit loggen |

## Koppelen

claude.ai → Settings → Connectors → Add custom connector → `https://<mini>.<tailnet>.ts.net/mcp`.
Claude opent de inlogpagina; vul het wachtwoord in. De connector werkt daarna ook in de
iPhone-app.

Alle koppelingen intrekken: stop de server en verwijder `oauth.sqlite`.
