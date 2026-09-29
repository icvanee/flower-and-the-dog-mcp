# Plan: MCP-server naar de Mac Mini

Doel: in de iPhone-app van Claude (spraak, liefst CarPlay) over het hardlopen praten:
recente trainingen opvragen en de dag erna in de auto notities dicteren.

## Besluiten (2026-09-29)

- Draait op de Mac Mini, niet meer op Railway. Railway blijft draaien tot de Mini-versie
  getest is; daarna gaat de Railway-service uit. Deze branch (`mini-oauth`) gaat pas naar
  `main` als Railway uit staat.
- Publiek via Tailscale Funnel op het `ts.net`-adres van de Mini. De DNS van
  `flowerandthedog.nl` blijft bij YourHosting; een Cloudflare-tunnel op eigen domein zou
  een nameserververhuizing vergen.
- OAuth via de autorisatieserver van de MCP SDK, met één gebruiker en een wachtwoordpagina.
- Secrets in `~/.config/flower-and-the-dog-mcp/env` (chmod 600), eventueel met op://-verwijzingen.
- Tools: carwash en de coachleo-placeholders blijven, `calculate` is weg.

## Stappen

0. **Werkt het end-to-end?** Server met OAuth en Streamable HTTP (klaar op deze branch),
   Funnel, connector in claude.ai. Test in de iPhone-app, in spraakmodus en in CarPlay
   voordat we verder bouwen.
1. **Trainingstools** op de Postgres van health-dashboard (`HEALTH_DATABASE_URL`, eigen
   rol `mcp`: SELECT op Run/RunSplit/StatusNote/TrainingPlanEntry, UPDATE alleen op
   `Run.notes` en `Run.updatedAt`, INSERT op StatusNote):
   - `recente_trainingen(aantal=5)`
   - `training_details(datum|id)`: splits, zones, notities
   - `notitie_bij_training(tekst, datum?)`: voegt toe met tijdstempel, overschrijft nooit;
     zonder datum de laatste run. Het antwoord noemt bij welke run het terechtkwam.
   - `status_notitie(tekst, categorie="general")`
   - `komend_schema(dagen=7)`
   De ingest-scripts van health-dashboard zetten `notes` nooit; zo moet het blijven.
2. **Op de Mini**: launchd-agent `nl.icvanee.mcp` in mac-mini-setup, plus `tailscale funnel --bg 8765`.
3. **Opruimen**: Railway uit, deze branch naar `main`, en het CNAME `mcp` bij YourHosting
   (wees nu naar Railway) verwijderen.
