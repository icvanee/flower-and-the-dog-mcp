"""
Agenda van Iwan via iCloud CalDAV (caldav.icloud.com).

Bewust via CalDAV en niet via de Agenda-app/EventKit: zo is er geen
TCC-toestemming op de Mini nodig. Inloggen met de Apple ID en een
app-specifiek wachtwoord (ICLOUD_CALDAV_USERNAME/PASSWORD, uit 1Password).

Alleen lezen en toevoegen; verwijderen en verplaatsen kan (nog) niet.
Antwoorden zijn korte Nederlandse tekst, omdat ze vaak worden voorgelezen.
"""

import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import caldav

# caldav logt bij "gerepareerde" iCalendar-data de hele afspraak; die horen niet in het serverlog
logging.getLogger("caldav").setLevel(logging.ERROR)

TZ = ZoneInfo("Europe/Amsterdam")
CALDAV_URL = "https://caldav.icloud.com"
WEEKDAGEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MAANDEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
MAX_DAGEN = 14
CALENDAR_CACHE_SECONDS = 600

_calendars: dict[str, caldav.Calendar] = {}
_calendars_at = 0.0


def _namen(env: str, standaard: str) -> list[str]:
    return [n.strip() for n in os.environ.get(env, standaard).split(",") if n.strip()]


def _standaard_agendas() -> list[str]:
    return _namen("AGENDA_CALENDARS", "home,Family,Coach Leo")


def _extra_agendas() -> list[str]:
    return _namen("AGENDA_EXTRA_CALENDARS", "Verjaardagen,Feestdagen")


def _alle_agendas() -> dict[str, caldav.Calendar]:
    """Agenda's per naam (kleine letters), een paar minuten gecachet."""
    global _calendars, _calendars_at
    if _calendars and time.monotonic() - _calendars_at < CALENDAR_CACHE_SECONDS:
        return _calendars
    username = os.environ.get("ICLOUD_CALDAV_USERNAME", "")
    password = os.environ.get("ICLOUD_CALDAV_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("ICLOUD_CALDAV_USERNAME/PASSWORD zijn niet ingesteld")
    client = caldav.DAVClient(url=CALDAV_URL, username=username, password=password)
    _calendars = {(c.get_display_name() or "").strip().lower(): c for c in client.principal().calendars()}
    _calendars_at = time.monotonic()
    return _calendars


# ─── Datums en opmaak ──────────────────────────────────────────────────────────

def _vandaag() -> date:
    return datetime.now(TZ).date()


def _parse_datum(tekst: str | None, standaard: date | None = None) -> date:
    if not tekst:
        if standaard is None:
            raise ValueError("Geen datum opgegeven.")
        return standaard
    t = tekst.strip().lower()
    relatief = {"vandaag": 0, "morgen": 1, "overmorgen": 2, "gisteren": -1}
    if t in relatief:
        return _vandaag() + timedelta(days=relatief[t])
    try:
        return date.fromisoformat(t)
    except ValueError:
        raise ValueError(f"Datum '{tekst}' begrijp ik niet. Gebruik vandaag, morgen of JJJJ-MM-DD.")


def _parse_tijd(tekst: str) -> tuple[int, int]:
    t = tekst.strip().lower().replace(".", ":").replace("u", ":").rstrip(":")
    uur, _, minuut = t.partition(":")
    try:
        h, m = int(uur), int(minuut or 0)
    except ValueError:
        raise ValueError(f"Tijd '{tekst}' begrijp ik niet. Gebruik bijvoorbeeld 14:30.")
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"Tijd '{tekst}' bestaat niet.")
    return h, m


def _dag(d: date) -> str:
    return f"{WEEKDAGEN[d.weekday()]} {d.day} {MAANDEN[d.month - 1]}"


def _lokaal(dt: datetime) -> datetime:
    # Zwevende tijden (zonder tijdzone) lezen we als Nederlandse tijd
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


# ─── Afspraken ophalen ─────────────────────────────────────────────────────────

def _afspraken(agendas: list[str], van: datetime, tot: datetime) -> tuple[list[dict], list[str]]:
    """Afspraken in [van, tot), herhalingen uitgeklapt. Geeft (afspraken, onbekende agenda's)."""
    alle = _alle_agendas()
    resultaat, onbekend = [], []
    for naam in agendas:
        cal = alle.get(naam.lower())
        if cal is None:
            onbekend.append(naam)
            continue
        for obj in cal.search(event=True, expand=True, start=van, end=tot):
            comp = obj.icalendar_component
            begin = comp.decoded("dtstart")
            if "dtend" in comp:
                eind = comp.decoded("dtend")
            elif "duration" in comp:
                eind = begin + comp.decoded("duration")
            else:
                eind = begin + (timedelta(days=1) if not isinstance(begin, datetime) else timedelta(0))
            hele_dag = not isinstance(begin, datetime)
            if not hele_dag:
                begin, eind = _lokaal(begin), _lokaal(eind)
            resultaat.append({
                "titel": str(comp.get("summary", "(geen titel)")),
                "agenda": cal.get_display_name() or naam,
                "locatie": str(comp.get("location", "")).strip(),
                "hele_dag": hele_dag,
                "begin": begin,
                "eind": eind,
            })
    resultaat.sort(key=sorteer)
    return resultaat, onbekend


def sorteer(a: dict):
    """Per dag: eerst hele-dag-afspraken, dan op begintijd."""
    return (_begindag(a), not a["hele_dag"], 0 if a["hele_dag"] else a["begin"].hour * 60 + a["begin"].minute)


def _met_werk(afspraken: list[dict], van: datetime, tot: datetime) -> tuple[list[dict], str | None]:
    """Voegt de werkagenda (ICS, alleen lezen) toe, zonder dubbelingen."""
    from tools import werkagenda  # hier, want werkagenda importeert deze module
    werk, melding = werkagenda.afspraken(van, tot)
    alle = werkagenda.zonder_dubbele(afspraken + werk)
    alle.sort(key=sorteer)
    return alle, melding


def _begindag(a: dict) -> date:
    return a["begin"] if a["hele_dag"] else a["begin"].date()


def _regel(a: dict, toon_dag: bool = False) -> str:
    if a["hele_dag"]:
        laatste = a["eind"] - timedelta(days=1)
        tijd = "hele dag" if laatste <= a["begin"] else f"hele dag t/m {_dag(laatste)}"
    else:
        tijd = f"{a['begin']:%H:%M}–{a['eind']:%H:%M}"
        if a["eind"].date() != a["begin"].date():
            tijd = f"{a['begin']:%H:%M} t/m {_dag(a['eind'].date())} {a['eind']:%H:%M}"
    locatie = f", {a['locatie']}" if a["locatie"] else ""
    dag = f"{_dag(_begindag(a))} " if toon_dag else ""
    return f"{dag}{tijd}: {a['titel']} ({a['agenda']}{locatie})"


def _agenda_sync(datum: str | None, tot: str | None, dagen: int | None, ook_verjaardagen: bool) -> str:
    begin = _parse_datum(datum, _vandaag())
    if tot:
        einde = _parse_datum(tot)
    elif dagen:
        einde = begin + timedelta(days=max(1, dagen) - 1)
    else:
        einde = begin
    if einde < begin:
        return "De einddatum ligt voor de begindatum."
    if (einde - begin).days >= MAX_DAGEN:
        einde = begin + timedelta(days=MAX_DAGEN - 1)
        afgekapt = f" (ingekort tot {MAX_DAGEN} dagen)"
    else:
        afgekapt = ""

    agendas = _standaard_agendas() + (_extra_agendas() if ook_verjaardagen else [])
    van = datetime.combine(begin, datetime.min.time(), TZ)
    tot_dt = datetime.combine(einde + timedelta(days=1), datetime.min.time(), TZ)
    afspraken, onbekend = _afspraken(agendas, van, tot_dt)
    afspraken, werk_melding = _met_werk(afspraken, van, tot_dt)
    # Onbekende extra agenda's (verjaardagen/feestdagen) zijn vaak geen CalDAV-agenda; niet melden
    onbekend = [n for n in onbekend if n in _standaard_agendas()]

    periode = _dag(begin) if begin == einde else f"{_dag(begin)} t/m {_dag(einde)}"
    if not afspraken:
        tekst = f"Geen afspraken op {periode}{afgekapt}."
    else:
        regels = []
        huidige = None
        for a in afspraken:
            dag = _begindag(a)
            if begin != einde and dag != huidige:
                regels.append(f"{_dag(max(dag, begin))}:")
                huidige = dag
            regels.append(("- " if begin != einde else "") + _regel(a))
        kop = f"Afspraken {periode}{afgekapt}:" if begin != einde else f"Afspraken op {periode}:"
        tekst = kop + "\n" + "\n".join(regels)
    if onbekend:
        tekst += f"\n(Agenda niet gevonden: {', '.join(onbekend)}.)"
    if werk_melding:
        tekst += f"\n({werk_melding})"
    return tekst


async def agenda(datum: str | None = None, tot: str | None = None, dagen: int | None = None,
                 ook_verjaardagen: bool = False) -> str:
    try:
        return await asyncio.to_thread(_agenda_sync, datum, tot, dagen, ook_verjaardagen)
    except ValueError as e:
        return str(e)


# ─── Afspraak plannen ──────────────────────────────────────────────────────────

def _plannen_sync(titel: str, datum: str, starttijd: str | None, duur_minuten: int, hele_dag: bool,
                  agenda_naam: str, locatie: str | None, notitie: str | None, bevestigd: bool) -> str:
    titel = titel.strip()
    if not titel:
        return "Geen titel opgegeven, niets opgeslagen."
    dag = _parse_datum(datum)
    if not hele_dag and not starttijd:
        return "Geen starttijd opgegeven. Geef een tijd, of plan het als hele dag."

    alle = _alle_agendas()
    cal = alle.get(agenda_naam.strip().lower())
    if cal is None:
        if agenda_naam.strip().lower() == "werk":
            return "In de werkagenda kan ik niets zetten, die kan ik alleen lezen."
        return f"Agenda '{agenda_naam}' bestaat niet. Kies uit: {', '.join(_standaard_agendas())}."

    if hele_dag:
        begin, eind = dag, dag + timedelta(days=1)
        wanneer = f"op {_dag(dag)}, hele dag"
        van = datetime.combine(dag, datetime.min.time(), TZ)
        tot = van + timedelta(days=1)
    else:
        h, m = _parse_tijd(starttijd)
        duur = max(5, duur_minuten or 60)
        begin = datetime.combine(dag, datetime.min.time(), TZ).replace(hour=h, minute=m)
        eind = begin + timedelta(minutes=duur)
        wanneer = f"op {_dag(dag)} van {begin:%H:%M} tot {eind:%H:%M}"
        van, tot = begin, eind

    samenvatting = f"'{titel}' {wanneer} in agenda {cal.get_display_name() or agenda_naam}"
    if locatie:
        samenvatting += f", locatie {locatie.strip()}"

    overlap, _ = _afspraken(_standaard_agendas(), van, tot)
    overlap, _ = _met_werk(overlap, van, tot)
    if not hele_dag:
        overlap = [a for a in overlap if not a["hele_dag"]]
    waarschuwing = ""
    if overlap:
        waarschuwing = " Let op, dit overlapt met: " + "; ".join(_regel(a) for a in overlap) + "."

    if not bevestigd:
        return (f"Nog niet opgeslagen. Lees dit voor en vraag om een duidelijk ja: {samenvatting}."
                f"{waarschuwing} Roep daarna opnieuw aan met bevestigd=true.")

    velden = {"summary": titel, "dtstart": begin, "dtend": eind}
    if locatie:
        velden["location"] = locatie.strip()
    if notitie:
        velden["description"] = notitie.strip()
    cal.add_event(**velden)
    return f"Opgeslagen: {samenvatting}.{waarschuwing}"


async def afspraak_plannen(titel: str, datum: str, starttijd: str | None = None, duur_minuten: int = 60,
                           hele_dag: bool = False, agenda_naam: str = "home", locatie: str | None = None,
                           notitie: str | None = None, bevestigd: bool = False) -> str:
    try:
        return await asyncio.to_thread(_plannen_sync, titel, datum, starttijd, duur_minuten, hele_dag,
                                       agenda_naam, locatie, notitie, bevestigd)
    except ValueError as e:
        return f"Niets opgeslagen. {e}"
