# Plan: MCP-server naar de Mac Mini

Doel: in de iPhone-app van Claude (spraak, liefst CarPlay) over het hardlopen praten:
recente trainingen opvragen en de dag erna in de auto notities dicteren.

## Besluiten (2026-09-29)

- Draait op de Mac Mini, niet meer op Railway. De Railway-service is op 2026-10-04
  verwijderd (n8n en Postgres op Railway blijven); alles staat op `main`.
- Publiek via Tailscale Funnel op het `ts.net`-adres van de Mini. De DNS van
  `flowerandthedog.nl` blijft bij YourHosting; een Cloudflare-tunnel op eigen domein zou
  een nameserververhuizing vergen.
- OAuth via de autorisatieserver van de MCP SDK, met één gebruiker en een wachtwoordpagina.
- Secrets in `~/.config/flower-and-the-dog-mcp/env` (chmod 600), eventueel met op://-verwijzingen.
- Tools: carwash blijft; `calculate` en de coachleo-placeholders zijn weg (het schema komt uit health-dashboard).

## Stappen

0. **Werkt het end-to-end?** (klaar: getypt, spraak en CarPlay) Server met OAuth en Streamable HTTP (klaar op deze branch),
   Funnel, connector in claude.ai. Test in de iPhone-app, in spraakmodus en in CarPlay
   voordat we verder bouwen.
1. **Trainingstools** (klaar) op de Postgres van health-dashboard (`HEALTH_DATABASE_URL`, eigen
   rol `mcp`: SELECT op Run/RunSplit/StatusNote/TrainingPlanEntry, UPDATE alleen op
   `Run.notes` en `Run.updatedAt`, INSERT op StatusNote):
   - `recente_trainingen(aantal=5)`
   - `training_details(datum|id)`: splits, zones, notities
   - `notitie_bij_training(tekst, datum?)`: voegt toe met tijdstempel, overschrijft nooit;
     zonder datum de laatste run. Het antwoord noemt bij welke run het terechtkwam.
   - `status_notitie(tekst, categorie="general")`
   - `komend_schema(dagen=7)`
   De ingest-scripts van health-dashboard zetten `notes` nooit; zo moet het blijven.
2. **Op de Mini** (klaar): launchd-agent `nl.icvanee.mcp` in mac-mini-setup, plus `tailscale funnel --bg 8765`.
3. **Opruimen**: Railway-service weg en alles op `main` (klaar). Nog: het CNAME `mcp` bij
   YourHosting verwijderen (wees naar Railway).
