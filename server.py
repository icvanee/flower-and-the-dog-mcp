import asyncio
import html
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from auth import SingleUserOAuthProvider
from tools import agenda, carwash, herinneringen, training

# ─── Config ────────────────────────────────────────────────────────────────────
# Op de Mini komen deze uit ~/.config/flower-and-the-dog-mcp/env (zie README).

HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_PORT", "8765"))
PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", f"http://localhost:{PORT}").rstrip("/")
DATA_DIR = Path(os.environ.get("MCP_DATA_DIR", Path.home() / ".local/share/flower-and-the-dog-mcp"))
ALLOWED_REDIRECT_HOSTS = os.environ.get(
    "MCP_ALLOWED_REDIRECT_HOSTS", "claude.ai,claude.com,localhost,127.0.0.1"
).split(",")

TZ = ZoneInfo("Europe/Amsterdam")
WEEKDAGEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("toolbox")

async def log_requests(ctx, call_next):
    """Logt elk MCP-verzoek, met de toolnaam bij tools/call."""
    if ctx.method == "tools/call":
        log.info("tools/call %s", (ctx.params or {}).get("name"))
    else:
        log.info("%s", ctx.method)
    return await call_next(ctx)

oauth = SingleUserOAuthProvider(
    db_path=DATA_DIR / "oauth.sqlite",
    password=os.environ.get("MCP_LOGIN_PASSWORD", ""),
    issuer_url=PUBLIC_URL,
    allowed_redirect_hosts=ALLOWED_REDIRECT_HOSTS,
)

mcp = MCPServer(
    name="flower-and-the-dog-toolbox",
    instructions=(
        "Persoonlijke tools van Iwan, vaak gebruikt via spraak (ook in de auto): houd antwoorden kort. "
        "Trainingen komen uit Iwans eigen trainingsdatabase. Vertelt Iwan hoe een training ging, "
        "sla dat dan op met notitie_bij_training; gaat het niet over één training (heup, slaap, "
        "hoe hij zich voelt), gebruik status_notitie. Zeg daarna kort wat er is opgeslagen. "
        "Voor de agenda en herinneringen: lees een nieuwe afspraak of herinnering altijd eerst voor "
        "en sla hem pas op na een duidelijk ja."
    ),
    auth_server_provider=oauth,
    auth=AuthSettings(
        issuer_url=PUBLIC_URL,
        resource_server_url=f"{PUBLIC_URL}/mcp",
        validate_token_resource=False,
        client_registration_options=ClientRegistrationOptions(enabled=True),
        revocation_options=RevocationOptions(enabled=True),
    ),
    middleware=[log_requests],
)

# ─── Algemene tools ────────────────────────────────────────────────────────────

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
def get_current_datetime() -> str:
    """Geeft de huidige datum en tijd in Nederland. Gebruik dit om 'gisteren' of 'vorige week' om te rekenen naar een datum."""
    now = datetime.now(TZ)
    return f"Het is {WEEKDAGEN[now.weekday()]} {now:%Y-%m-%d}, {now:%H:%M} (Europe/Amsterdam)."

# ─── Carwash ───────────────────────────────────────────────────────────────────

@mcp.tool(name="carwash_get_history", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
async def _carwash_get_history(days: int = 365) -> dict:
    """Geeft de wasgeschiedenis van de auto terug via het Carwash Kleiboer klantenportaal. Gebruik dit om te vragen wanneer de auto voor het laatst gewassen is."""
    return await carwash.carwash_get_history(days=days)

# ─── Trainingen (health-dashboard) ─────────────────────────────────────────────

LEZEN = ToolAnnotations(read_only_hint=True, open_world_hint=False)
TOEVOEGEN = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

Datum = Annotated[str | None, Field(description="Datum als JJJJ-MM-DD. Reken 'gisteren' e.d. om met get_current_datetime. Leeg = meest recente training.")]
TrainingId = Annotated[str | None, Field(description="Id van de training, alleen nodig als er op één dag meerdere zijn.")]
Soort = Annotated[str, Field(description="Workouttype: running (standaard), walking, cycling, swimming, traditionalStrengthTraining, ... of 'alle'.")]

@mcp.tool(annotations=LEZEN)
async def recente_trainingen(
    aantal: Annotated[int, Field(description="Hoeveel trainingen, 1 tot 30.")] = 5,
    soort: Soort = "running",
) -> str:
    """Iwans meest recente trainingen (standaard hardlopen): datum, afstand, tijd, tempo, gemiddelde hartslag en of er al een notitie is."""
    return await training.recente_trainingen(aantal, soort)

@mcp.tool(annotations=LEZEN)
async def training_details(datum: Datum = None, training_id: TrainingId = None, soort: Soort = "running") -> str:
    """Alles over één training van Iwan: tempo, hartslag, zones, splits per km, wat er gepland stond en de notities."""
    return await training.training_details(datum, training_id, soort)

@mcp.tool(annotations=TOEVOEGEN)
async def notitie_bij_training(
    tekst: Annotated[str, Field(description="Hoe de training ging, beknopt en in Iwans eigen woorden: gevoel, pijntjes, omstandigheden.")],
    datum: Datum = None,
    training_id: TrainingId = None,
    soort: Soort = "running",
) -> str:
    """Slaat op hoe een training ging, bij die training in Iwans trainingsdatabase. Vult aan met een tijdstempel en overschrijft nooit bestaande notities. Zonder datum: de meest recente training."""
    return await training.notitie_bij_training(tekst, datum, training_id, soort)

@mcp.tool(annotations=TOEVOEGEN)
async def status_notitie(
    tekst: Annotated[str, Field(description="De notitie, beknopt en in Iwans eigen woorden.")],
    categorie: Annotated[str, Field(description="'hip' voor de heup, anders 'general' of een ander kort label.")] = "general",
) -> str:
    """Slaat een notitie van vandaag op die niet bij één training hoort, zoals hoe de heup voelt, slaap of algemene conditie."""
    return await training.status_notitie(tekst, categorie)

@mcp.tool(annotations=LEZEN)
async def status_notities(
    dagen: Annotated[int, Field(description="Hoeveel dagen terug, 1 tot 365.")] = 30,
    categorie: Annotated[str | None, Field(description="Alleen deze categorie, bijvoorbeeld 'hip'. Leeg = alle.")] = None,
) -> str:
    """Iwans statusnotities van de afgelopen tijd, zoals het verloop van de heupblessure."""
    return await training.status_notities(dagen, categorie)

@mcp.tool(annotations=LEZEN)
async def trainingsschema(dagen: Annotated[int, Field(description="Hoeveel dagen vooruit, 1 tot 60.")] = 7) -> str:
    """Wat er de komende dagen op Iwans trainingsschema staat."""
    return await training.trainingsschema(dagen)

# ─── Agenda (iCloud CalDAV) ────────────────────────────────────────────────────

AgendaDatum = Annotated[str | None, Field(description="'vandaag', 'morgen', 'overmorgen' of JJJJ-MM-DD.")]

@mcp.tool(name="agenda", annotations=LEZEN)
async def _agenda(
    datum: AgendaDatum = None,
    tot: Annotated[str | None, Field(description="Laatste dag van een periode (JJJJ-MM-DD, inclusief). Leeg = alleen 'datum'.")] = None,
    dagen: Annotated[int | None, Field(description="In plaats van 'tot': aantal dagen vanaf 'datum', maximaal 14.")] = None,
    ook_verjaardagen: Annotated[bool, Field(description="Ook verjaardagen en feestdagen meenemen, als die agenda's bestaan.")] = False,
) -> str:
    """Iwans afspraken voor een dag of periode (maximaal 14 dagen), uit de agenda's home, Family en Coach Leo. Zonder datum: vandaag."""
    return await agenda.agenda(datum, tot, dagen, ook_verjaardagen)

@mcp.tool(annotations=TOEVOEGEN)
async def afspraak_plannen(
    titel: Annotated[str, Field(description="Korte titel van de afspraak.")],
    datum: Annotated[str, Field(description="'vandaag', 'morgen', 'overmorgen' of JJJJ-MM-DD.")],
    starttijd: Annotated[str | None, Field(description="Begintijd, bijvoorbeeld 14:30. Leeg alleen bij hele_dag.")] = None,
    duur_minuten: Annotated[int, Field(description="Duur in minuten.")] = 60,
    hele_dag: Annotated[bool, Field(description="Afspraak voor de hele dag, zonder tijd.")] = False,
    agenda_naam: Annotated[str, Field(description="Agenda: home (standaard), Family of Coach Leo.")] = "home",
    locatie: Annotated[str | None, Field(description="Optioneel: waar.")] = None,
    notitie: Annotated[str | None, Field(description="Optioneel: extra informatie.")] = None,
    bevestigd: Annotated[bool, Field(description="Alleen true nadat Iwan de voorgelezen afspraak duidelijk met ja heeft bevestigd.")] = False,
) -> str:
    """Zet een nieuwe afspraak in Iwans agenda. Roep eerst aan met bevestigd=false: dat slaat niets op en geeft een samenvatting (met eventuele overlap). Lees die voor, vraag om een duidelijk ja, en roep pas daarna aan met bevestigd=true. Kan geen afspraken verwijderen of verplaatsen."""
    return await agenda.afspraak_plannen(titel, datum, starttijd, duur_minuten, hele_dag, agenda_naam,
                                         locatie, notitie, bevestigd)

# ─── Herinneringen (Apple Herinneringen-app) ───────────────────────────────────

@mcp.tool(name="herinnering_maken", annotations=TOEVOEGEN)
async def _herinnering_maken(
    titel: Annotated[str, Field(description="Wat Iwan moet onthouden of doen.")],
    datum: Annotated[str | None, Field(description="Optioneel: 'vandaag', 'morgen', 'overmorgen' of JJJJ-MM-DD.")] = None,
    tijd: Annotated[str | None, Field(description="Optioneel: tijd van de melding, bijvoorbeeld 9:00. Zonder datum: vandaag.")] = None,
    lijst: Annotated[str, Field(description="Lijst: Herinneringen (standaard), India, Verjaardagslijst, L'Estartit. Family alleen als Iwan dat expliciet vraagt, die is gedeeld met het gezin.")] = herinneringen.STANDAARD_LIJST,
    notitie: Annotated[str | None, Field(description="Optioneel: extra informatie.")] = None,
    bevestigd: Annotated[bool, Field(description="Alleen true nadat Iwan de voorgelezen herinnering duidelijk met ja heeft bevestigd.")] = False,
) -> str:
    """Zet een herinnering in Apple Herinneringen, met een melding als er een tijd is. Roep eerst aan met bevestigd=false: dat slaat niets op en geeft een samenvatting. Lees die voor, vraag om een duidelijk ja, en roep pas daarna aan met bevestigd=true. Kan geen herinneringen verwijderen of wijzigen."""
    return await herinneringen.herinnering_maken(titel, datum, tijd, lijst, notitie, bevestigd)

# ─── HTTP-routes buiten MCP ────────────────────────────────────────────────────

@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok", "server": "flower-and-the-dog-toolbox"})

LOGIN_PAGE = """<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flower and the Dog Toolbox</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background: #f5f5f2; color: #222;
         display: flex; min-height: 100vh; margin: 0; align-items: center; justify-content: center; }}
  form {{ background: #fff; padding: 2rem; border-radius: 12px; width: min(22rem, 100% - 2rem);
          box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
  h1 {{ font-size: 1.2rem; margin-top: 0; }}
  input, button {{ width: 100%; box-sizing: border-box; font-size: 1rem; padding: .7rem; margin-top: .6rem;
                   border-radius: 8px; border: 1px solid #ccc; }}
  button {{ background: #222; color: #fff; border: 0; }}
  .error {{ color: #b00; }}
</style></head><body>
<form method="post">
  <h1>Toegang geven aan Claude</h1>
  <p>Log in om Claude toegang te geven tot de Flower and the Dog Toolbox.</p>
  {error}
  <input type="hidden" name="request" value="{request_id}">
  <input type="password" name="password" placeholder="Wachtwoord" autofocus autocomplete="current-password">
  <button type="submit">Toestaan</button>
</form></body></html>"""

def _login_page(request_id: str, error: str = "", status_code: int = 200) -> HTMLResponse:
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(
        LOGIN_PAGE.format(request_id=html.escape(request_id), error=error_html),
        status_code=status_code,
        headers={"X-Frame-Options": "DENY", "Cache-Control": "no-store"},
    )

@mcp.custom_route("/login", methods=["GET", "POST"])
async def login(request: Request) -> Response:
    if request.method == "GET":
        request_id = request.query_params.get("request", "")
    else:
        form = await request.form()
        request_id = str(form.get("request", ""))

    if not oauth.login_request_exists(request_id):
        return HTMLResponse("Dit inlogverzoek is verlopen. Verbind opnieuw vanuit Claude.", status_code=400)
    if request.method == "GET":
        return _login_page(request_id)

    redirect = oauth.complete_login(request_id, str(form.get("password", "")))
    if redirect is None:
        await asyncio.sleep(2)  # remt het raden van wachtwoorden af
        return _login_page(request_id, "Onjuist wachtwoord.", status_code=401)
    return RedirectResponse(redirect, status_code=302)

# ─── App ───────────────────────────────────────────────────────────────────────

public_host = urlparse(PUBLIC_URL).netloc
app = mcp.streamable_http_app(
    host=HOST,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[public_host, "127.0.0.1:*", "localhost:*"],
        allowed_origins=[PUBLIC_URL, "https://claude.ai", "https://claude.com", "http://localhost:*", "http://127.0.0.1:*"],
    ),
)

if __name__ == "__main__":
    log_config = uvicorn.config.LOGGING_CONFIG
    for formatter in log_config["formatters"].values():
        formatter["fmt"] = "%(asctime)s " + formatter["fmt"]
    uvicorn.run(app, host=HOST, port=PORT, proxy_headers=True, forwarded_allow_ips="127.0.0.1", log_config=log_config)
