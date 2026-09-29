import asyncio
import html
import logging
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from auth import SingleUserOAuthProvider
from tools import carwash, coachleo

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
    instructions="Persoonlijke tools van Iwan. Antwoorden worden vaak voorgelezen: houd ze kort.",
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

@mcp.tool()
def get_current_datetime() -> str:
    """Geeft de huidige datum en tijd in Nederland. Gebruik dit om 'gisteren' of 'vorige week' om te rekenen naar een datum."""
    now = datetime.now(TZ)
    return f"Het is {WEEKDAGEN[now.weekday()]} {now:%Y-%m-%d}, {now:%H:%M} (Europe/Amsterdam)."

# ─── Carwash ───────────────────────────────────────────────────────────────────

@mcp.tool(name="carwash_get_history")
async def _carwash_get_history(days: int = 365) -> dict:
    """Geeft de wasgeschiedenis van de auto terug via het Carwash Kleiboer klantenportaal. Gebruik dit om te vragen wanneer de auto voor het laatst gewassen is."""
    return await carwash.carwash_get_history(days=days)

# ─── Coach Leo (placeholders) ──────────────────────────────────────────────────

@mcp.tool(name="coachleo_get_plan")
async def _coachleo_get_plan(week_offset: int = 0) -> dict:
    """Get the training plan from Coach Leo for a given week. 0 = current week, 1 = next week, -1 = last week."""
    return await coachleo.coachleo_get_plan(week_offset)

@mcp.tool(name="coachleo_get_upcoming_races")
async def _coachleo_get_upcoming_races() -> dict:
    """Get upcoming races from Coach Leo"""
    return await coachleo.coachleo_get_upcoming_races()

@mcp.tool(name="coachleo_log_run")
async def _coachleo_log_run(distance_km: float, duration_minutes: float, notes: str = "") -> dict:
    """Log a completed run in Coach Leo"""
    return await coachleo.coachleo_log_run(distance_km, duration_minutes, notes)

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
