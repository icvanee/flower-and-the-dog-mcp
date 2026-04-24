"""
Carwash Kleiboer — transactiehistorie tool.

Stel deze env vars in Railway:
  CARWASH_USERNAME   →  icvanee@gmail.com
  CARWASH_PASSWORD   →  <jouw wachtwoord>
"""

import os
from datetime import datetime, date
from io import BytesIO

import httpx
import openpyxl
from bs4 import BeautifulSoup

BASE_URL = "https://carwashkleiboer.carwash-cms.com/customerportal"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _parse_excel(content: bytes) -> list[dict]:
    """Lees de Excel export en geef een lijst van wasbeurtdicts terug."""
    wb = openpyxl.load_workbook(BytesIO(content))
    ws = wb.active
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not any(row):
            continue
        # Kolommen: vestiging, datum/tijd, aantal, omschrijving, bedrag, ...
        vestiging, datum_tijd, aantal, omschrijving, bedrag, *rest = row
        rows.append({
            "vestiging": vestiging,
            "datum_tijd": str(datum_tijd) if datum_tijd else None,
            "aantal": aantal,
            "omschrijving": omschrijving,
            "bedrag": bedrag,
        })
    return rows


async def carwash_get_history(days: int = 365) -> dict:
    """
    Log in op het Carwash Kleiboer klantenportaal en geef de wasgeschiedenis terug.

    Args:
        days: Hoeveel dagen terug te kijken (standaard 365).

    Returns:
        Dict met 'last_wash', 'total_washes', en 'history' (lijst van wasbeurt-dicts).
    """
    username = os.environ.get("CARWASH_USERNAME", "")
    password = os.environ.get("CARWASH_PASSWORD", "")
    if not username or not password:
        return {
            "status": "error",
            "message": "CARWASH_USERNAME en/of CARWASH_PASSWORD zijn niet ingesteld als env var.",
        }

    date_start = "1-1-2020"
    date_end = date.today().strftime("%-d-%-m-%Y")

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30.0) as client:
        # Stap 1: haal loginpagina op (zodat cookie-check slaagt)
        await client.get(f"{BASE_URL}/Account/Login")

        # Stap 2: loginpagina + CSRF token
        login_page = await client.get(
            f"{BASE_URL}/Account/Login",
            params={"returnurl": "/customerportal/Profile", "checked": "1"},
        )
        soup = BeautifulSoup(login_page.text, "html.parser")
        csrf_input = soup.find("input", {"name": "__RequestVerificationToken"})
        if not csrf_input:
            return {"status": "error", "message": "Loginpagina niet bereikbaar of structuur gewijzigd."}
        csrf = csrf_input["value"]

        # Stap 3: inloggen
        await client.post(
            f"{BASE_URL}/Account/Login",
            data={
                "__RequestVerificationToken": csrf,
                "UserName": username,
                "Password": password,
            },
        )

        # Stap 4: verse CSRF token voor transactiepagina
        trans_page = await client.get(f"{BASE_URL}/Transaction")
        soup2 = BeautifulSoup(trans_page.text, "html.parser")
        csrf2_input = soup2.find("input", {"name": "__RequestVerificationToken"})
        if not csrf2_input:
            return {"status": "error", "message": "Inloggen mislukt of transactiepagina niet bereikbaar."}
        csrf2 = csrf2_input["value"]

        # Stap 5: Excel export downloaden
        response = await client.post(
            f"{BASE_URL}/Transaction",
            data={
                "__RequestVerificationToken": csrf2,
                "DateStart": date_start,
                "DateEnd": date_end,
                "Export": "",
            },
        )

    if "application/vnd" not in response.headers.get("content-type", ""):
        return {
            "status": "error",
            "message": "Geen Excel ontvangen — mogelijk inlogprobleem of gewijzigde site.",
            "content_type": response.headers.get("content-type"),
        }

    history = _parse_excel(response.content)

    # Meest recente wasbeurt bovenaan
    history.sort(key=lambda r: r["datum_tijd"] or "", reverse=True)

    last_wash = history[0]["datum_tijd"] if history else None

    return {
        "status": "ok",
        "last_wash": last_wash,
        "total_washes": len(history),
        "history": history,
    }
