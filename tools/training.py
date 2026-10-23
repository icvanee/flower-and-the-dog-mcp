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
    "avgCadenceSpm", "maxCadenceSpm", "avgStrideLengthM", "stepCount",
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


# Het schema heeft wedstrijden twee keer: in hun fase (bv. "Fase 1") en in het blok
# "Wedstrijden", met dezelfde datum en hetzelfde type. Toon zo'n dag één keer, met de
# rij uit de fase, gemarkeerd als wedstrijd. `{waar}` is de datumvoorwaarde op p.
PLAN_QUERY = """
SELECT p.date, p.type, p."plannedKm", p.description, p.status, p.block,
       (p.block = 'Wedstrijden' OR EXISTS (
           SELECT 1 FROM "TrainingPlanEntry" w WHERE w.block = 'Wedstrijden' AND w.date = p.date AND w.type = p.type
       )) AS wedstrijd
FROM "TrainingPlanEntry" p
WHERE {waar}
  AND (p.block <> 'Wedstrijden' OR NOT EXISTS (
      SELECT 1 FROM "TrainingPlanEntry" o WHERE o.block <> 'Wedstrijden' AND o.date = p.date AND o.type = p.type
  ))
ORDER BY p.date, p.id
"""


def _plan_regel(r: dict) -> str:
    """'Easy 6,0 km (dalweek)' of 'Wedstrijd: BAX 7,5K 7,5 km (…)'."""
    km = f" {_km(r['plannedKm'] * 1000)} km" if r["plannedKm"] else ""
    omschrijving = f" ({r['description']})" if r["description"] else ""
    return f"{'Wedstrijd: ' if r['wedstrijd'] else ''}{r['type']}{km}{omschrijving}"


# Cadans onder de 100 stappen per minuut is een meetfout (er staan nullen in de data)
MIN_CADANS = 100


def _cadans(run: dict) -> int | None:
    v = run.get("avgCadenceSpm")
    return round(v) if v and v >= MIN_CADANS else None


def _staplengte(m: float | None) -> str:
    return f"{m:.2f}".replace(".", ",") + " m"


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
        if r["workoutType"] == "running":
            cadans = _cadans(r)
            regel = regel[:-1] + (f", cadans {cadans}." if cadans else ", geen cadans gemeten.")
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
        plan = await (await conn.execute(PLAN_QUERY.format(waar="p.date = %s"), (run["date"],))).fetchall()
        cadans_per_km = await _cadans_per_km(conn, run["id"])

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
    if run["workoutType"] == "running":
        cadans = _cadans(run)
        if cadans:
            delen = [f"Cadans gemiddeld {cadans}"]
            if run["maxCadenceSpm"] and run["maxCadenceSpm"] >= MIN_CADANS:
                delen.append(f"max {round(run['maxCadenceSpm'])}")
        else:
            delen = ["Geen cadans gemeten"]
        if run["avgStrideLengthM"]:
            delen.append(f"staplengte {_staplengte(run['avgStrideLengthM'])}")
        if cadans and run["stepCount"]:
            delen.append(f"{round(run['stepCount'])} stappen")
        regels.append(", ".join(delen) + ".")
        if cadans_per_km:
            regels.append("Cadans per km: " + "; ".join(f"{km}: {c}" for km, c in cadans_per_km) + ".")
    if splits:
        regels.append("Per km: " + "; ".join(
            f"{s['km']}: {_duur(s['paceSecPerKm'])}" + (f" ({round(s['avgHrBpm'])})" if s["avgHrBpm"] else "")
            for s in splits
        ) + ".")
    for p in plan:
        regels.append(f"Gepland: {_plan_regel(p)}.")
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
            PLAN_QUERY.format(waar="p.date >= %(van)s AND p.date < %(van)s + %(dagen)s::int"),
            {"van": vandaag, "dagen": dagen},
        )).fetchall()
        if not rows:
            laatste = await (await conn.execute('SELECT max(date) AS d FROM "TrainingPlanEntry"')).fetchone()
    if not rows:
        tot = f" Het schema loopt tot {_datum(laatste['d'])}." if laatste and laatste["d"] else ""
        return f"Niets gepland voor de komende {dagen} dagen.{tot}"
    return "\n".join(f"{_datum(r['date'])}: {_plan_regel(r)}." for r in rows)


async def geplande_trainingen(dag: date) -> list[str]:
    """De trainingen die op `dag` in het schema staan, als korte zinnen (voor mijn_dag)."""
    async with await _connect() as conn:
        rows = await (await conn.execute(PLAN_QUERY.format(waar="p.date = %s"), (dag,))).fetchall()
    return [_plan_regel(r) for r in rows]


async def _cadans_per_km(conn, run_id: str) -> list[tuple[int, int]]:
    """Gemiddelde cadans per kilometer uit RunSample, als de rol daar mag lezen; anders leeg."""
    mag = await (await conn.execute("SELECT has_table_privilege(current_user, '\"RunSample\"', 'SELECT') AS mag")).fetchone()
    if not mag["mag"]:
        return []
    rows = await (await conn.execute(
        'SELECT floor("distanceM" / 1000)::int + 1 AS km, avg("cadenceSpm") AS c FROM "RunSample" '
        'WHERE "runId" = %s AND "cadenceSpm" >= %s AND "distanceM" IS NOT NULL GROUP BY 1 '
        # Een restje na de laatste hele km (een paar meter) is geen km
        'HAVING max("distanceM") - min("distanceM") >= 200 ORDER BY 1',
        (run_id, MIN_CADANS),
    )).fetchall()
    return [(r["km"], round(r["c"])) for r in rows]


async def cadans_trend(maanden: int = 6, per: str = "maand", tempo_banden: bool = True) -> str:
    """Gemiddelde cadans per week of maand, met staplengte, tempo en hartslag; plus rustig vs. snel."""
    maanden = max(1, min(maanden, 60))
    eenheid = "week" if per == "week" else "month"
    async with await _connect() as conn:
        rows = await (await conn.execute(
            'SELECT date_trunc(%(eenheid)s, date)::date AS periode, count(*) AS n, '
            'avg("avgCadenceSpm") AS cadans, avg("avgStrideLengthM") AS stap, '
            'avg("avgPaceSecPerKm") AS tempo, avg("avgHeartRate") AS hartslag '
            'FROM "Run" WHERE "workoutType" = \'running\' AND "avgCadenceSpm" >= %(min)s '
            "AND date >= (current_date - make_interval(months => %(maanden)s)) "
            "GROUP BY 1 ORDER BY 1",
            {"eenheid": eenheid, "min": MIN_CADANS, "maanden": maanden},
        )).fetchall()
        banden = []
        if tempo_banden and rows:
            # Rustig/snel ten opzichte van Iwans eigen runs in deze periode (langzaamste en snelste derde)
            banden = await (await conn.execute(
                'WITH r AS (SELECT "avgCadenceSpm" c, "avgStrideLengthM" s, "avgPaceSecPerKm" p, "avgHeartRate" h '
                'FROM "Run" WHERE "workoutType" = \'running\' AND "avgCadenceSpm" >= %(min)s '
                'AND "avgPaceSecPerKm" IS NOT NULL AND date >= (current_date - make_interval(months => %(maanden)s))), '
                "g AS (SELECT percentile_cont(0.33) WITHIN GROUP (ORDER BY p) p33, "
                "percentile_cont(0.67) WITHIN GROUP (ORDER BY p) p67 FROM r) "
                "SELECT CASE WHEN p >= p67 THEN 'rustig' WHEN p <= p33 THEN 'snel' ELSE 'midden' END AS band, "
                "count(*) n, avg(c) c, avg(s) s, avg(p) p, avg(h) h, max(p33) p33, max(p67) p67 "
                "FROM r, g GROUP BY 1",
                {"min": MIN_CADANS, "maanden": maanden},
            )).fetchall()
        laatste = await (await conn.execute(
            'SELECT max(date) AS d FROM "Run" WHERE "workoutType" = \'running\' AND "avgCadenceSpm" >= %s', (MIN_CADANS,)
        )).fetchone()
        zonder = await (await conn.execute(
            'SELECT count(*) AS n FROM "Run" WHERE "workoutType" = \'running\' AND date > %s', (laatste["d"],)
        )).fetchone() if laatste["d"] else {"n": 0}

    if not rows:
        return f"Geen cadans gemeten in de afgelopen {maanden} maanden."

    def periode(d: date) -> str:
        return f"week van {d.day} {MAANDEN[d.month - 1]}" if eenheid == "week" else f"{MAANDEN[d.month - 1]} {d.year}"

    regels = [f"Cadans per {per}, laatste {maanden} maanden:"]
    for r in rows:
        stap = f", staplengte {_staplengte(r['stap'])}" if r["stap"] else ""
        hs = f", hartslag {round(r['hartslag'])}" if r["hartslag"] else ""
        tempo = f", tempo {_tempo(r['tempo'])}" if r["tempo"] else ""
        regels.append(f"{periode(r['periode'])}: {round(r['cadans'])}{stap}{tempo}{hs} ({r['n']} {'run' if r['n'] == 1 else 'runs'})")
    verschil = round(rows[-1]["cadans"]) - round(rows[0]["cadans"])
    if len(rows) > 1:
        richting = "gelijk gebleven" if verschil == 0 else (f"{abs(verschil)} hoger" if verschil > 0 else f"{abs(verschil)} lager")
        regels.append(f"Van {periode(rows[0]['periode'])} tot {periode(rows[-1]['periode'])}: {richting}.")
    per_band = {b["band"]: b for b in banden}
    if "rustig" in per_band and "snel" in per_band:
        rustig, snel = per_band["rustig"], per_band["snel"]
        regels.append(
            f"Rustige runs (tempo {_tempo(rustig['p67'])} of langzamer): cadans {round(rustig['c'])}, "
            f"staplengte {_staplengte(rustig['s'])}, hartslag {round(rustig['h'])}. "
            f"Snelle runs ({_tempo(snel['p33'])} of sneller): cadans {round(snel['c'])}, "
            f"staplengte {_staplengte(snel['s'])}, hartslag {round(snel['h'])}."
        )
    if zonder["n"]:
        regels.append(f"Let op: bij de {zonder['n']} runs na {_datum(laatste['d'])} is geen cadans gemeten.")
    return "\n".join(regels)
