"""
Werkagenda (Outlook/Exchange) uit een gepubliceerde ICS-feed, alleen lezen.

De feed-URL (WORK_CALENDAR_ICS_URL, uit 1Password) bevat een geheim token: hij komt
nooit in logs of antwoorden. Daarom staat de httpx-logger hier op WARNING (die logt
anders elke aanvraag met URL) en geven foutmeldingen alleen het soort fout.

De feed wordt een kwartier in het geheugen gecachet. Lukt ophalen niet, dan gebruiken
we de vorige versie en melden we dat. Herhalingen (RRULE, EXDATE, RECURRENCE-ID)
klapt recurring_ical_events uit; Outlook-tijdzones staan als VTIMEZONE in de feed.
"""

import logging
import os
import time
from datetime import date, datetime, timedelta

import httpx
import icalendar
import recurring_ical_events

from tools.agenda import TZ, _lokaal

CACHE_SECONDEN = 15 * 60
LABEL = "werk"

logging.getLogger("httpx").setLevel(logging.WARNING)

_feed: icalendar.Calendar | None = None
_feed_at = 0.0
_fout: str | None = None


def ingesteld() -> bool:
    return bool(os.environ.get("WORK_CALENDAR_ICS_URL"))


def _haal_op() -> None:
    global _feed, _feed_at, _fout
    url = os.environ["WORK_CALENDAR_ICS_URL"]
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True)
        r.raise_for_status()
        _feed = icalendar.Calendar.from_ical(r.content)
        _feed_at = time.monotonic()
        _fout = None
    except httpx.HTTPStatusError as e:
        _fout = f"de werkagenda gaf HTTP {e.response.status_code}"
    except httpx.HTTPError as e:
        _fout = f"de werkagenda is niet bereikbaar ({type(e).__name__})"
    except ValueError:
        _fout = "de werkagenda kon niet worden gelezen"


def afspraken(van: datetime, tot: datetime) -> tuple[list[dict], str | None]:
    """Werkafspraken in [van, tot) in dezelfde vorm als agenda._afspraken, plus een melding als
    de gegevens oud zijn of ontbreken."""
    if not ingesteld():
        return [], None
    if _feed is None or time.monotonic() - _feed_at > CACHE_SECONDEN:
        _haal_op()
    if _feed is None:
        return [], f"Werkagenda ontbreekt: {_fout}."
    melding = None
    if _fout:
        melding = f"Werkagenda van {round((time.monotonic() - _feed_at) / 60)} minuten geleden: {_fout}."

    resultaat = []
    for ev in recurring_ical_events.of(_feed).between(van, tot):
        if str(ev.get("status", "")).upper() == "CANCELLED":
            continue
        begin = ev.decoded("dtstart")
        if "dtend" in ev:
            eind = ev.decoded("dtend")
        elif "duration" in ev:
            eind = begin + ev.decoded("duration")
        else:
            eind = begin + (timedelta(days=1) if not isinstance(begin, datetime) else timedelta(0))
        hele_dag = not isinstance(begin, datetime)
        if not hele_dag:
            begin, eind = _lokaal(begin), _lokaal(eind)
        privé = str(ev.get("class", "")).upper() == "PRIVATE"
        resultaat.append({
            "titel": "Privé-afspraak" if privé else str(ev.get("summary", "(geen titel)")),
            "agenda": LABEL,
            "locatie": "" if privé else str(ev.get("location", "")).strip(),
            "hele_dag": hele_dag,
            "begin": begin,
            "eind": eind,
        })
    return resultaat, melding


def zonder_dubbele(lijst: list[dict]) -> list[dict]:
    """Haalt afspraken weg die met dezelfde titel en begintijd al in de lijst staan
    (bijvoorbeeld een werkuitnodiging die ook in iCloud is doorgestuurd)."""
    gezien, uit = set(), []
    for a in lijst:
        sleutel = (a["titel"].strip().lower(), a["begin"].isoformat() if isinstance(a["begin"], (date, datetime)) else a["begin"])
        if sleutel in gezien:
            continue
        gezien.add(sleutel)
        uit.append(a)
    return uit
