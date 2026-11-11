"""
Wasmachine (Samsung, SmartThings) en vaatwasser (Bosch, Home Connect), alleen uitlezen.

De waarden komen van het home-dashboard (127.0.0.1:8787), dat ze uit Home Assistant
haalt. Bedienen kan bewust niet: de connector start of stopt geen apparaten.
De labels volgen het dashboard (static/index.html in home-devices).
"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from tools.lampen import DashboardFout, _http

TZ = ZoneInfo("Europe/Amsterdam")
APPARATEN = {"wasmachine": "sensor.wasmachine_washer_machine_state",
             "vaatwasser": "sensor.vaatwasser_operation_state"}

STAND = {"stop": "uit", "inactive": "uit", "ready": "aan en wacht", "delayedstart": "start uitgesteld", "run": "bezig",
         "pause": "gepauzeerd", "actionrequired": "heeft actie nodig", "finished": "klaar", "error": "heeft een storing",
         "aborting": "wordt afgebroken", "unavailable": "niet bereikbaar", "unknown": "onbekend"}
FASE = {"wash": "wassen", "pre_wash": "voorwas", "rinse": "spoelen", "spin": "centrifugeren", "drying": "drogen",
        "weight_sensing": "wegen", "delay_wash": "uitgesteld", "cooling": "afkoelen", "wrinkle_prevent": "kreukbescherming",
        "air_wash": "luchtwas", "ai_wash": "wassen", "ai_rinse": "spoelen", "ai_spin": "centrifugeren",
        "freeze_protection": "vorstbeveiliging"}
PROGRAMMA = {"eco_50": "Eco 50", "auto_2": "Auto", "intensiv_70": "Intensief 70", "quick_65": "Snel 65",
             "night_wash": "Nacht", "machine_care": "Machinereiniging", "pre_rinse": "Voorspoelen"}
BEZIG = ("run", "pause", "delayedstart")


def _tijd(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(iso).astimezone(TZ) if iso else None
    except ValueError:
        return None


def _nog(t: datetime) -> str:
    minuten = max(0, round((t - datetime.now(TZ)).total_seconds() / 60))
    if minuten >= 60:
        return f"nog {minuten // 60} uur en {minuten % 60} minuten" if minuten % 60 else f"nog {minuten // 60} uur"
    return f"nog {minuten} minuten"


def _programma(p: str | None) -> str | None:
    if not p or p in ("unknown", "unavailable"):
        return None
    k = p.rsplit("_program_", 1)[-1]
    return PROGRAMMA.get(k, k.replace("_", " ").capitalize())


def _zin(naam: str, e: dict | None) -> str:
    if not e:
        return f"De {naam} ken ik niet."
    st, a = e.get("state"), e.get("appliance") or {}
    werkwoord = "staat" if st in ("stop", "inactive", "ready", "pause") else "is"
    if st in ("actionrequired", "error"):
        werkwoord = ""
    delen = [" ".join(x for x in ("De", naam, werkwoord, STAND.get(st, st)) if x)]
    if st in BEZIG:
        if a.get("kind") == "washer" and FASE.get(a.get("job")):
            delen.append(f"aan het {FASE[a['job']]}" if a["job"] in ("wash", "rinse", "spin", "drying") else FASE[a["job"]])
        if prog := _programma(a.get("program")):
            delen.append(f"programma {prog}")
        if a.get("progress") not in (None, "", "unknown") and str(a["progress"]).replace(".", "").isdigit():
            delen.append(f"{round(float(a['progress']))}% klaar")
        t = _tijd(a.get("finish"))
        if t and t > datetime.now(TZ):
            delen.append(f"klaar om {t:%H:%M}, {_nog(t)}")
    zin = ", ".join(delen) + "."
    waarschuwing = []
    if a.get("door") == "open":
        waarschuwing.append("de deur staat open")
    if a.get("salt") in ("present", "on"):
        waarschuwing.append("het zout is bijna op")
    if a.get("rinse_aid") in ("present", "on"):
        waarschuwing.append("het glansspoelmiddel is bijna op")
    if waarschuwing:
        zin += " Let op: " + " en ".join(waarschuwing) + "."
    return zin


def _apparaten_sync(welke: str | None) -> str:
    ents = _http("/api/state").get("entities", {})
    namen = list(APPARATEN)
    if welke:
        w = welke.strip().lower()
        namen = [n for n in APPARATEN if n.startswith(w[:3])] or namen
    return " ".join(_zin(n, ents.get(APPARATEN[n])) for n in namen)


async def apparaten(welke: str | None = None) -> str:
    try:
        return await asyncio.to_thread(_apparaten_sync, welke)
    except DashboardFout as e:
        return f"Apparaten niet beschikbaar: {e}."
