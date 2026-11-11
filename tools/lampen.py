"""
Lampen in huis via het home-dashboard op de Mini (home-devices, 127.0.0.1:8787).

De connector praat bewust niet zelf met Home Assistant en heeft geen HA-token:
het dashboard bepaalt welke apparaten bediend mogen worden (alleen wat op de
plattegrond staat). Hier worden alleen lampen (light.*) gelezen en geschakeld:
aan, uit en helderheid. Niets anders.
"""

import asyncio
import difflib
import json
import os
import unicodedata
import urllib.error
import urllib.request

DASHBOARD = os.environ.get("HOME_DASHBOARD_URL", "http://127.0.0.1:8787").rstrip("/")
TIMEOUT_SECONDEN = 10


class DashboardFout(Exception):
    pass


def _http(pad: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{DASHBOARD}{pad}", data=data, method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDEN) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise DashboardFout(f"het dashboard gaf fout {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise DashboardFout("het home-dashboard is niet bereikbaar") from e


def _norm(tekst: str) -> str:
    zonder_accent = "".join(c for c in unicodedata.normalize("NFKD", tekst) if not unicodedata.combining(c))
    return " ".join(zonder_accent.lower().replace("-", " ").split())


def _lampen() -> list[dict]:
    """Alle lampen op de plattegrond: entity_id, naam, kamer, stand, helderheid (%) en of het een groep is."""
    st = _http("/api/state")
    kamer_van = {e: kamer for kamer, ents in st.get("rooms", {}).items() for e in ents}
    lampen = []
    for eid, e in st.get("entities", {}).items():
        if not eid.startswith("light.") or eid not in kamer_van:
            continue
        b = e.get("brightness")
        lampen.append({"id": eid, "naam": e.get("name") or eid, "kamer": kamer_van[eid], "aan": e.get("state") == "on",
                       "pct": round(b / 2.55) if e.get("state") == "on" and b else None,
                       "groep": bool(e.get("group")), "beschikbaar": e.get("state") in ("on", "off")})
    return lampen


def _omschrijving(l: dict) -> str:
    if not l["beschikbaar"]:
        return f"{l['naam']}: niet bereikbaar"
    if not l["aan"]:
        return f"{l['naam']}: uit"
    return f"{l['naam']}: aan" + (f" op {l['pct']}%" if l["pct"] else "")


def _zoek(naam: str, lampen: list[dict]) -> tuple[dict | None, list[dict]]:
    """Lamp bij een gesproken naam ("mancave", "plafondlamp mancave", "keuken").
    Geeft (lamp, []) bij één treffer, (None, kandidaten) als het niet eenduidig is."""
    n = _norm(naam).removeprefix("de ").removeprefix("het ")
    n_kort = n  # "keuken lamp" / "mancave licht" -> "keuken" / "mancave"
    for woord in ("lampen", "lamp", "licht", "verlichting"):
        if n.endswith(" " + woord):
            n_kort = n[: -len(woord) - 1].strip()
            break
    sleutels = {}
    for l in lampen:
        for s in (l["naam"], f"{l['kamer']} {l['naam']}", f"{l['naam']} {l['kamer']}"):
            sleutels.setdefault(_norm(s), []).append(l)
    for zoek in (n, n_kort):
        if len(sleutels.get(zoek, [])) == 1:
            return sleutels[zoek][0], []
    # een kamernaam: de groep van die kamer, of de enige lamp daar
    for zoek in (n, n_kort):
        in_kamer = [l for l in lampen if _norm(l["kamer"]) == zoek]
        groepen = [l for l in in_kamer if l["groep"]]
        if len(groepen) == 1:
            return groepen[0], []
        if len(in_kamer) == 1:
            return in_kamer[0], []
        if in_kamer:
            return None, in_kamer
    # spraakherkenning: wat speling
    dichtbij = difflib.get_close_matches(n, sleutels.keys(), n=3, cutoff=0.7)
    treffers = list({l["id"]: l for k in dichtbij for l in sleutels[k]}.values())
    if len(treffers) == 1:
        return treffers[0], []
    return None, treffers


def _lampen_sync(kamer: str | None) -> str:
    lampen = _lampen()
    if kamer:
        k = _norm(kamer)
        lampen = [l for l in lampen if _norm(l["kamer"]) == k] or [l for l in lampen if k in _norm(l["kamer"])]
        if not lampen:
            return f"Kamer '{kamer}' ken ik niet."
    if not lampen:
        return "Er zijn geen lampen."
    per_kamer: dict[str, list[str]] = {}
    for l in sorted(lampen, key=lambda l: (l["kamer"], not l["groep"], l["naam"])):
        per_kamer.setdefault(l["kamer"], []).append(_omschrijving(l))
    return " ".join(f"{k}: {'; '.join(v)}." for k, v in per_kamer.items())


def _lamp_sync(naam: str, actie: str, helderheid: int | None) -> str:
    actie = _norm(actie)
    if actie not in ("aan", "uit"):
        return "Actie moet 'aan' of 'uit' zijn."
    lampen = _lampen()
    lamp, kandidaten = _zoek(naam, lampen)
    if lamp is None:
        if kandidaten:
            opties = ", ".join(f"{l['naam']} ({l['kamer']})" for l in kandidaten)
            return f"Welke bedoel je: {opties}?"
        return f"Lamp '{naam}' ken ik niet. Vraag de lijst op met de tool lampen."
    if not lamp["beschikbaar"]:
        return f"{lamp['naam']} is nu niet bereikbaar, er is niets geschakeld."
    eid = lamp["id"]
    if actie == "uit":
        if not lamp["aan"]:
            return f"{lamp['naam']} stond al uit."
        _http("/api/turn_off", {"entity_id": eid})
        return f"{lamp['naam']} is uit."
    if helderheid is not None:
        pct = max(1, min(100, int(helderheid)))
        _http("/api/brightness", {"entity_id": eid, "pct": pct})
        return f"{lamp['naam']} staat aan op {pct}%."
    if lamp["aan"]:
        return _omschrijving(lamp).replace(": aan", " stond al aan", 1) + "."
    _http("/api/toggle", {"entity_id": eid})  # het dashboard heeft geen kale turn_on; de lamp staat zeker uit
    return f"{lamp['naam']} is aan."


async def lampen(kamer: str | None = None) -> str:
    try:
        return await asyncio.to_thread(_lampen_sync, kamer)
    except DashboardFout as e:
        return f"Lampen niet beschikbaar: {e}."


async def lamp(naam: str, actie: str, helderheid: int | None = None) -> str:
    try:
        return await asyncio.to_thread(_lamp_sync, naam, actie, helderheid)
    except DashboardFout as e:
        return f"Niets geschakeld: {e}."
