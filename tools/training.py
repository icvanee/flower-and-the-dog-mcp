"""
Trainingen uit de Postgres van health-dashboard (~/Source/health-dashboard).

Verbindt als rol `mcp` via HEALTH_DATABASE_URL. Die rol mag lezen, alleen
Run.notes/updatedAt wijzigen en StatusNote-rijen toevoegen. Notities worden
altijd aangevuld, nooit overschreven; de ingest-scripts van health-dashboard
raken Run.notes en StatusNote-rijen met een andere bron dan "logbook" niet aan,
dus ze overleven een her-import. Het runlog uit het overdrachtsdocument staat
apart in Run."logbookNotes"; dat leest deze server alleen.

Antwoorden zijn korte Nederlandse tekst, omdat ze vaak worden voorgelezen.
"""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

TZ = ZoneInfo("Europe/Amsterdam")
WEEKDAGEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MAANDEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
SOORTEN = {
    "running": "hardlopen",
    "walking": "wandelen",
    "cycling": "fietsen",
    "swimming": "zwemmen",
    "hiking": "hiken",
    "traditionalStrengthTraining": "krachttraining",
    "functionalStrengthTraining": "krachttraining",
    "highIntensityIntervalTraining": "HIIT",
    "underwaterDiving": "duiken",
    "sailing": "zeilen",
    "yoga": "yoga",
    "tennis": "tennis",
}

# startTime staat als UTC zonder tijdzone in de database
RUN_COLUMNS = """
    id, date, "workoutType", "distanceMeters", "durationSeconds", "avgHeartRate",
    "maxHeartRate", "avgPaceSecPerKm", "hrDriftBpm", "elevationGainMeters",
    "hrZone1Sec", "hrZone2Sec", "hrZone3Sec", "hrZone4Sec", "hrZone5Sec",
    "weatherTempCelsius", source, notes, "logbookNotes",
    ("startTime" AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Amsterdam' AS start_local
"""


async def _connect() -> psycopg.AsyncConnection:
    url = os.environ.get("HEALTH_DATABASE_URL", "")
    if not url:
        raise RuntimeError("HEALTH_DATABASE_URL is niet ingesteld")
    return await psycopg.AsyncConnection.connect(url, row_factory=dict_row, autocommit=True)


# ─── Opmaak ────────────────────────────────────────────────────────────────────

def _datum(d: date) -> str:
    return f"{WEEKDAGEN[d.weekday()]} {d.day} {MAANDEN[d.month - 1]}"


def _duur(seconds: float) -> str:
    s = round(seconds)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _km(meters: float) -> str:
    return f"{meters / 1000:.1f}".replace(".", ",")


def _tempo(sec_per_km: float) -> str:
    return f"{_duur(sec_per_km)}/km"


def _soort(workout_type: str) -> str:
    return SOORTEN.get(workout_type, workout_type)


def _samenvatting(run: dict) -> str:
    """Eén regel: wanneer, wat, hoe ver, hoe snel, hartslag."""
    tijd = f" {run['start_local']:%H:%M}" if run["start_local"] else ""
    delen = [f"{_datum(run['date'])}{tijd}: {_soort(run['workoutType'])}"]
    afstand = f"{_km(run['distanceMeters'])} km " if run["distanceMeters"] else ""
    delen.append(f"{afstand}in {_duur(run['durationSeconds'])}")
    if run["avgPaceSecPerKm"] and run["distanceMeters"]:
        delen.append(f"tempo {_tempo(run['avgPaceSecPerKm'])}")
    if run["avgHeartRate"]:
        delen.append(f"hartslag {round(run['avgHeartRate'])}")
    return ", ".join(delen) + "."


def _parse_datum(datum: str | None) -> date | None:
    if not datum:
        return None
    try:
        return date.fromisoformat(datum)
    except ValueError:
        raise ValueError(f"Datum '{datum}' is geen JJJJ-MM-DD. Reken 'gisteren' e.d. eerst om met get_current_datetime.")


async def _vind_training(conn, datum: str | None, training_id: str | None, soort: str) -> tuple[dict | None, str | None]:
    """Zoekt één training op id, op datum, of de meest recente. Geeft (training, foutmelding)."""
    if training_id:
        rows = await (await conn.execute(f'SELECT {RUN_COLUMNS} FROM "Run" WHERE id = %s', (training_id,))).fetchall()
        return (rows[0], None) if rows else (None, f"Geen training met id {training_id}.")

    dag = _parse_datum(datum)
    soort_filter = "" if soort == "alle" else 'AND "workoutType" = %(soort)s'
    if dag is None:
        rows = await (await conn.execute(
            f'SELECT {RUN_COLUMNS} FROM "Run" WHERE true {soort_filter} '
            'ORDER BY date DESC, "startTime" DESC NULLS LAST LIMIT 1',
            {"soort": soort},
        )).fetchall()
        return (rows[0], None) if rows else (None, "Geen trainingen gevonden.")

    rows = await (await conn.execute(
        f'SELECT {RUN_COLUMNS} FROM "Run" WHERE date = %(dag)s {soort_filter} ORDER BY "startTime" NULLS LAST',
        {"dag": dag, "soort": soort},
    )).fetchall()
    if not rows:
        return None, f"Geen training ({_soort(soort) if soort != 'alle' else 'van welke soort ook'}) op {_datum(dag)}."
    if len(rows) > 1:
        opties = "\n".join(f"- id {r['id']}: {_samenvatting(r)}" for r in rows)
        return None, f"Op {_datum(dag)} zijn {len(rows)} trainingen. Welke bedoel je?\n{opties}"
    return rows[0], None


# ─── Tools ─────────────────────────────────────────────────────────────────────

async def recente_trainingen(aantal: int = 5, soort: str = "running") -> str:
    aantal = max(1, min(aantal, 30))
    soort_filter = "" if soort == "alle" else 'WHERE "workoutType" = %(soort)s'
    async with await _connect() as conn:
        rows = await (await conn.execute(
            f'SELECT {RUN_COLUMNS} FROM "Run" {soort_filter} '
            'ORDER BY date DESC, "startTime" DESC NULLS LAST LIMIT %(aantal)s',
            {"soort": soort, "aantal": aantal},
        )).fetchall()
    if not rows:
        return "Geen trainingen gevonden."
    regels = []
    for r in rows:
        regel = _samenvatting(r)
        if r["notes"] or r["logbookNotes"]:
            regel += " Heeft een notitie."
        regels.append(regel)
    return "\n".join(regels)


async def training_details(datum: str | None = None, training_id: str | None = None, soort: str = "running") -> str:
    async with await _connect() as conn:
        run, fout = await _vind_training(conn, datum, training_id, soort)
        if fout:
            return fout
        splits = await (await conn.execute(
            'SELECT km, "paceSecPerKm", "avgHrBpm" FROM "RunSplit" WHERE "runId" = %s ORDER BY km', (run["id"],)
        )).fetchall()
        plan = await (await conn.execute(
            'SELECT type, "plannedKm", description FROM "TrainingPlanEntry" WHERE date = %s', (run["date"],)
        )).fetchall()

    regels = [_samenvatting(run)]
    extra = []
    if run["maxHeartRate"]:
        extra.append(f"max hartslag {run['maxHeartRate']}")
    if run["hrDriftBpm"] is not None:
        extra.append(f"hartslagdrift {run['hrDriftBpm']:+.0f}")
    if run["elevationGainMeters"]:
        extra.append(f"{round(run['elevationGainMeters'])} m stijging")
    if run["weatherTempCelsius"] is not None:
        extra.append(f"{round(run['weatherTempCelsius'])} graden")
    if extra:
        regels.append(", ".join(extra).capitalize() + ".")

    # Seconden per zone (Z1..Z5, grenzen uit het SMO Papendal), als aandeel van de tijd
    zone_sec = [run[f"hrZone{i}Sec"] or 0 for i in range(1, 6)]
    totaal = sum(zone_sec)
    if totaal:
        regels.append("Hartslagzones: " + ", ".join(
            f"zone {i} {round(100 * sec / totaal)}%" for i, sec in enumerate(zone_sec, 1) if round(100 * sec / totaal)
        ) + ".")
    if splits:
        regels.append("Per km: " + "; ".join(
            f"{s['km']}: {_duur(s['paceSecPerKm'])}" + (f" ({round(s['avgHrBpm'])})" if s["avgHrBpm"] else "")
            for s in splits
        ) + ".")
    for p in plan:
        gepland = f" {_km(p['plannedKm'] * 1000)} km" if p["plannedKm"] else ""
        regels.append(f"Gepland: {p['type']}{gepland}" + (f" ({p['description']})" if p["description"] else "") + ".")
    if run["logbookNotes"]:
        regels.append(f"Uit het runlog:\n{run['logbookNotes']}")
    if run["notes"]:
        regels.append(f"Notities:\n{run['notes']}")
    if not run["logbookNotes"] and not run["notes"]:
        regels.append("Nog geen notities.")
    regels.append(f"(id {run['id']})")
    return "\n".join(regels)


async def notitie_bij_training(tekst: str, datum: str | None = None, training_id: str | None = None, soort: str = "running") -> str:
    tekst = tekst.strip()
    if not tekst:
        return "Lege notitie, niets opgeslagen."
    regel = f"[{datetime.now(TZ):%Y-%m-%d %H:%M}] {tekst}"
    async with await _connect() as conn:
        run, fout = await _vind_training(conn, datum, training_id, soort)
        if fout:
            return "Niets opgeslagen. " + fout
        # In één statement aanvullen, zodat gelijktijdige notities elkaar niet overschrijven
        await conn.execute(
            'UPDATE "Run" SET notes = CASE WHEN coalesce(notes, \'\') = \'\' THEN %(regel)s '
            "ELSE notes || E'\\n' || %(regel)s END, "
            '"updatedAt" = now() AT TIME ZONE \'UTC\' WHERE id = %(id)s',
            {"regel": regel, "id": run["id"]},
        )
    return f"Opgeslagen bij {_samenvatting(run)[:-1]}."


async def status_notitie(tekst: str, categorie: str = "general") -> str:
    tekst = tekst.strip()
    if not tekst:
        return "Lege notitie, niets opgeslagen."
    vandaag = datetime.now(TZ).date()
    async with await _connect() as conn:
        await conn.execute(
            'INSERT INTO "StatusNote" (date, category, note, source) VALUES (%s, %s, %s, \'mcp\')',
            (vandaag, categorie, tekst),
        )
    return f"Statusnotitie ({categorie}) opgeslagen voor {_datum(vandaag)}."


async def status_notities(dagen: int = 30, categorie: str | None = None) -> str:
    dagen = max(1, min(dagen, 365))
    async with await _connect() as conn:
        rows = await (await conn.execute(
            'SELECT date, category, note FROM "StatusNote" '
            "WHERE date >= current_date - %(dagen)s::int AND (%(categorie)s::text IS NULL OR category = %(categorie)s) "
            'ORDER BY date DESC, "createdAt" DESC',
            {"dagen": dagen, "categorie": categorie},
        )).fetchall()
    if not rows:
        return f"Geen statusnotities in de afgelopen {dagen} dagen."
    return "\n".join(f"{_datum(r['date'])} ({r['category']}): {r['note']}" for r in rows)


async def trainingsschema(dagen: int = 7) -> str:
    dagen = max(1, min(dagen, 60))
    vandaag = datetime.now(TZ).date()
    async with await _connect() as conn:
        rows = await (await conn.execute(
            'SELECT block, date, type, "plannedKm", description, status FROM "TrainingPlanEntry" '
            "WHERE date >= %(van)s AND date < %(van)s + %(dagen)s::int ORDER BY date",
            {"van": vandaag, "dagen": dagen},
        )).fetchall()
        if not rows:
            laatste = await (await conn.execute('SELECT max(date) AS d FROM "TrainingPlanEntry"')).fetchone()
    if not rows:
        tot = f" Het schema loopt tot {_datum(laatste['d'])}." if laatste and laatste["d"] else ""
        return f"Niets gepland voor de komende {dagen} dagen.{tot}"
    regels = []
    for r in rows:
        km = f" {_km(r['plannedKm'] * 1000)} km" if r["plannedKm"] else ""
        omschrijving = f" ({r['description']})" if r["description"] else ""
        regels.append(f"{_datum(r['date'])}: {r['type']}{km}{omschrijving}.")
    return "\n".join(regels)
