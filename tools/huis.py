"""
Alles wat het home-dashboard (127.0.0.1:8787) van het huis laat zien, als korte
zinnen per kamer: lampen, schakelaars (zoals de schuifdeur), sensoren, energie,
beweging, deurbel, media, wie er thuis is, kachel en apparaten. Alleen uitlezen.

Scènes, camera's, de gong en de Mac Mini zelf blijven weg: daar valt niets uit te lezen.
"""

import asyncio
import unicodedata

from tools import apparaten
from tools.lampen import DashboardFout, _http, _omschrijving

OVERSLAAN = ("scene.", "camera.", "siren.", "macmini.")
NAMEN = {  # nettere namen voor wat Home Assistant in het Engels noemt
    "sensor.p1_meter_3c39e72bd15c_active_power": "Stroomverbruik nu",
    "sensor.p1_meter_3c39e72bd15c_active_power_l1": None,  # zelfde als het totaal (één fase)
    "sensor.gas_meter_gas": "Gasmeterstand",
    "sensor.hue_outdoor_motion_sensor_1_temperature": "Buitentemperatuur",
    "binary_sensor.hue_outdoor_motion_sensor_1_motion": "Beweging tuin",
    "binary_sensor.oprit_motion": "Beweging oprit",
    "binary_sensor.bel_voordeur_motion": "Beweging bij de voordeur",
    "binary_sensor.bel_voordeur_ding": "Deurbel",
    "sensor.oprit_illuminance": "Licht op de oprit",
}
MEDIA = {"playing": "speelt", "paused": "gepauzeerd", "idle": "stil", "on": "aan", "off": "uit", "standby": "stand-by"}


def _norm(t: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def _getal(v) -> str:
    x = float(v)
    return (f"{x:.1f}" if abs(x) < 100 and x != int(x) else f"{round(x)}").replace(".", ",")


def _regel(eid: str, e: dict) -> str | None:
    naam = NAMEN.get(eid, e.get("name") or eid)
    if naam is None:
        return None
    dom, st = eid.split(".")[0], e.get("state")
    if st in ("unavailable", "unknown") and dom not in ("light",):
        return f"{naam}: niet bereikbaar"
    if e.get("appliance"):
        zin = apparaten._zin(naam.lower(), e).removeprefix("De ").rstrip(".")
        return zin[:1].upper() + zin[1:]
    if dom == "light":
        b = e.get("brightness")
        return _omschrijving({"naam": naam, "beschikbaar": st in ("on", "off"), "aan": st == "on",
                              "pct": round(b / 2.55) if st == "on" and b else None})
    if dom == "switch":
        return f"{naam}: {'aan' if st == 'on' else 'uit'}"
    if dom == "person":
        return f"{naam}: {'thuis' if st == 'home' else 'weg' if st == 'not_home' else st}"
    if dom == "binary_sensor":
        dc = e.get("device_class")
        if dc == "heat":
            return f"{naam}: {'stookt' if st == 'on' else 'stookt niet'}"
        if dc == "motion":
            return f"{naam}: {'nu beweging' if st == 'on' else 'geen beweging'}"
        if eid.endswith("_ding"):
            return f"{naam}: {'wordt nu aangebeld' if st == 'on' else 'niet aangebeld'}"
        return f"{naam}: {'aan' if st == 'on' else 'uit'}"
    if dom == "climate":
        if st == "off":
            return f"{naam}: uit" + (f", gemeten {_getal(e['current_temperature'])} °C" if e.get("current_temperature") else "")
        return f"{naam}: aan, ingesteld op {_getal(e['temperature'])} °C" if e.get("temperature") else f"{naam}: aan"
    if dom == "media_player":
        s = f"{naam}: {MEDIA.get(st, st)}"
        if st in ("playing", "paused") and e.get("media_title"):
            s += f" ({e['media_title']})"
        if e.get("volume") is not None and st not in ("off", "standby"):
            s += f", volume {round(float(e['volume']) * 100)}%"
        return s
    if dom == "number":
        return f"{naam}: {_getal(st)}"
    if dom == "sensor":
        try:
            return f"{naam}: {_getal(st)} {e.get('unit') or ''}".rstrip()
        except (TypeError, ValueError):
            return f"{naam}: {st}"
    return f"{naam}: {st}"


def _huis_sync(kamer: str | None, zoek: str | None) -> str:
    st = _http("/api/state")
    ents = st.get("entities", {})
    kamer_van = {e: k for k, es in st.get("rooms", {}).items() for e in es}
    per_kamer: dict[str, list[str]] = {}
    for eid, e in ents.items():
        if eid.startswith(OVERSLAAN):
            continue
        k = kamer_van.get(eid) or ("Wie is thuis" if eid.startswith("person.") else "Overig")
        if kamer and _norm(kamer) not in _norm(k):
            continue
        regel = _regel(eid, e)
        if regel is None or (zoek and _norm(zoek) not in _norm(regel) and _norm(zoek) not in _norm(eid)):
            continue
        per_kamer.setdefault(k, []).append(regel)
    if not per_kamer:
        wat = " en ".join(x for x in (f"kamer '{kamer}'" if kamer else "", f"'{zoek}'" if zoek else "") if x)
        return f"Niets gevonden voor {wat}. Kamers: {', '.join(sorted(st.get('rooms', {})))}."
    return " ".join(f"{k}: {'; '.join(sorted(set(v)))}." for k, v in sorted(per_kamer.items()))


async def huis(kamer: str | None = None, zoek: str | None = None) -> str:
    try:
        return await asyncio.to_thread(_huis_sync, kamer, zoek)
    except DashboardFout as e:
        return f"Het huis is nu niet uit te lezen: {e}."
