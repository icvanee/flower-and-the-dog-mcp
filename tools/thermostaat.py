"""
Temperatuur in huis en de Resideo/Honeywell-thermostaat.

Uitlezen gaat via het home-dashboard (127.0.0.1:8787); de thermostaat- en
HomePod-waarden komen daar via homepod_sync.py uit Apple Home in.

Instellen kan alleen via Opdrachten: "Control Home" kent geen variabele
temperatuur, dus er is per waarde een opdracht "Thermostaat 20", "Thermostaat 20,5",
... Alleen opdrachten met precies die vorm worden uitgevoerd (veiligheidsgrens),
binnen 15-25 °C, en pas na bevestiging. De ingestelde doeltemperatuur is niet
uit te lezen (Apple Home geeft hem niet door aan de opdracht "HomePod klimaat").
"""

import asyncio
import re
import subprocess
import time

from tools.lampen import DashboardFout, _http

PATROON = re.compile(r"^Thermostaat (\d{2})(?:,(5))?$")
MIN_C, MAX_C = 15.0, 25.0
CACHE_SECONDEN = 600
TIMEOUT_SECONDEN = 20

SENSOREN = [  # (entity_id, hoe het voorgelezen wordt)
    ("sensor.thermostaat_keuken_temperatuur", "thermostaat (keuken)"),
    ("sensor.homepod_woonkamer_temperatuur", "woonkamer"),
    ("sensor.homepod_slaapkamer_temperatuur", "slaapkamer"),
]
STOOKT = "binary_sensor.thermostaat_keuken_stookt"
KACHEL = "climate.verwarming_gang"

_opdrachten: dict[float, str] = {}
_opdrachten_at = 0.0


def _graden(x: float) -> str:
    return f"{x:g}".replace(".", ",") + " graden"


def _lijst() -> dict[float, str]:
    """Temperatuur -> exacte opdrachtnaam, alleen opdrachten 'Thermostaat NN' of 'Thermostaat NN,5'."""
    global _opdrachten, _opdrachten_at
    if _opdrachten and time.monotonic() - _opdrachten_at < CACHE_SECONDEN:
        return _opdrachten
    p = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=TIMEOUT_SECONDEN)
    if p.returncode != 0:
        raise RuntimeError("Opdrachten kon de lijst niet geven.")
    gevonden = {}
    for naam in p.stdout.splitlines():
        m = PATROON.match(naam.strip())
        if m:
            t = int(m.group(1)) + (0.5 if m.group(2) else 0.0)
            if MIN_C <= t <= MAX_C:
                gevonden[t] = naam.strip()
    _opdrachten, _opdrachten_at = gevonden, time.monotonic()
    return gevonden


def _waarden(lijst: dict[float, str]) -> str:
    return ", ".join(f"{t:g}".replace(".", ",") for t in sorted(lijst)) or "geen"


def _temperatuur_sync() -> str:
    ents = _http("/api/state").get("entities", {})
    delen = []
    for eid, label in SENSOREN:
        e = ents.get(eid)
        if e and e.get("state") not in (None, "unknown", "unavailable"):
            delen.append(f"{label} {_graden(float(e['state']))}")
    zinnen = ["Binnen: " + ", ".join(delen) + "." if delen else "Geen binnentemperatuur beschikbaar."]
    stookt = ents.get(STOOKT, {}).get("state")
    if stookt in ("on", "off"):
        zinnen.append("De thermostaat stookt nu." if stookt == "on" else "De thermostaat stookt nu niet.")
    k = ents.get(KACHEL)
    if k and k.get("state") not in (None, "unavailable"):
        zinnen.append("Kachel in de gang: uit." if k["state"] == "off"
                      else f"Kachel in de gang: aan, ingesteld op {_graden(float(k['temperature']))}." if k.get("temperature")
                      else "Kachel in de gang: aan.")
    return " ".join(zinnen)


def _thermostaat_sync(temperatuur: float, bevestigd: bool) -> str:
    lijst = _lijst()
    if not lijst:
        return "Er zijn geen thermostaat-opdrachten. Maak in Opdrachten bijvoorbeeld 'Thermostaat 20'."
    t = round(float(temperatuur) * 2) / 2
    if t not in lijst:
        return f"{_graden(t)} kan ik niet instellen. Wel: {_waarden(lijst)} graden."
    opdracht = lijst[t]
    if not bevestigd:
        return (f"Nog niet uitgevoerd. Vraag: zal ik de thermostaat op {_graden(t)} zetten? "
                "Roep na een duidelijk ja opnieuw aan met bevestigd=true.")
    if not PATROON.match(opdracht):  # veiligheidsgrens: nooit een andere opdracht
        return "Dat is geen thermostaat-opdracht, ik voer het niet uit."
    try:
        p = subprocess.run(["shortcuts", "run", opdracht], capture_output=True, text=True, timeout=TIMEOUT_SECONDEN)
    except subprocess.TimeoutExpired:
        return f"De thermostaat reageerde niet binnen {TIMEOUT_SECONDEN} seconden."
    if p.returncode != 0:
        return "De thermostaat kon niet worden ingesteld."
    return f"De thermostaat staat op {_graden(t)}."


async def temperatuur() -> str:
    try:
        return await asyncio.to_thread(_temperatuur_sync)
    except DashboardFout as e:
        return f"Temperatuur niet beschikbaar: {e}."


async def thermostaat(temperatuur: float, bevestigd: bool = False) -> str:
    try:
        return await asyncio.to_thread(_thermostaat_sync, temperatuur, bevestigd)
    except (RuntimeError, subprocess.TimeoutExpired):
        return "Opdrachten reageert niet, er is niets ingesteld."
