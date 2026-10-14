"""
mijn_dag: een korte dagbriefing, vooral om voor te laten lezen in de auto.

Combineert de afspraken (iCloud-agenda's), de geplande training (schema in
health-dashboard) en de open herinneringen die die dag vervallen of al over tijd
zijn. Het weer haalt deze tool niet op; dat kan Claude met een weer-connector doen.

Afspraken komen uit AFSPRAAK_BRONNEN. Een extra bron (bijvoorbeeld de werkagenda
als ICS-URL) is een functie (van, tot) -> lijst afspraken in dezelfde vorm als
agenda._afspraken geeft: titel, agenda, locatie, hele_dag, begin, eind.
"""

import asyncio
from datetime import datetime, timedelta

from tools import agenda, herinneringen, training, werkagenda
from tools.agenda import TZ, _dag, _parse_datum, _regel, _vandaag


def _icloud(van: datetime, tot: datetime) -> tuple[list[dict], str | None]:
    afspraken, _ = agenda._afspraken(agenda._standaard_agendas(), van, tot)
    return afspraken, None


# Elke bron: (van, tot) -> (afspraken, melding of None)
AFSPRAAK_BRONNEN = [_icloud, werkagenda.afspraken]


def _afspraken_sync(van: datetime, tot: datetime) -> tuple[list[dict], list[str]]:
    alle, meldingen = [], []
    for bron in AFSPRAAK_BRONNEN:
        try:
            afspraken, melding = bron(van, tot)
            alle.extend(afspraken)
            if melding:
                meldingen.append(melding)
        except Exception as e:
            meldingen.append(f"{bron.__module__.rsplit('.', 1)[-1]}: {type(e).__name__}")
    alle = werkagenda.zonder_dubbele(alle)
    alle.sort(key=agenda.sorteer)
    return alle, meldingen


def _herinneringen_regels(dag) -> list[str]:
    items, leeftijd = herinneringen.open_herinneringen()
    if items is None:
        return ["Herinneringen worden nog geladen, vraag het zo nog eens."]
    eind = datetime.combine(dag + timedelta(days=1), datetime.min.time(), TZ)
    begin = datetime.combine(dag, datetime.min.time(), TZ)
    vandaag_items, over_tijd = [], []
    for h in items:
        if h["moment"] >= eind:
            continue
        familie = herinneringen._norm(h["lijst"]) == "family"
        if h["moment"] >= begin:
            vandaag_items.append(h)
        elif not familie:  # Family alleen als er iets van die dag in staat
            over_tijd.append(h)
    regels = []
    if vandaag_items:
        delen = [(h["titel"] if h["hele_dag"] else f"{h['moment']:%H:%M} {h['titel']}")
                 + ("" if herinneringen._norm(h["lijst"]) == "herinneringen" else f" ({h['lijst']})")
                 for h in sorted(vandaag_items, key=lambda h: h["moment"])]
        regels.append("Herinneringen: " + "; ".join(delen) + ".")
    if over_tijd:
        delen = [f"{h['titel']} (sinds {_dag(h['moment'].date())})" for h in sorted(over_tijd, key=lambda h: h["moment"])]
        regels.append(f"Over tijd: " + "; ".join(delen) + ".")
    if leeftijd is not None and leeftijd > 30:
        regels.append(f"(Herinneringen zijn {round(leeftijd)} minuten oud.)")
    return regels


async def mijn_dag(dag: str | None = None) -> str:
    try:
        datum = _parse_datum(dag, _vandaag())
    except ValueError as e:
        return str(e)
    van = datetime.combine(datum, datetime.min.time(), TZ)
    tot = van + timedelta(days=1)

    afspraken, fouten = await asyncio.to_thread(_afspraken_sync, van, tot)
    try:
        trainingen = await training.geplande_trainingen(datum)
    except Exception as e:
        trainingen = []
        fouten.append(f"trainingsschema: {e}")

    kop = "Vandaag" if datum == _vandaag() else ("Morgen" if datum == _vandaag() + timedelta(days=1) else None)
    regels = [f"{kop}, {_dag(datum)}." if kop else f"{_dag(datum).capitalize()}."]

    met_tijd = [a for a in afspraken if not a["hele_dag"]]
    hele_dag = [a for a in afspraken if a["hele_dag"]]
    # Vandaag alleen wat nog komt of nu bezig is
    voorbij = 0
    if datum == _vandaag():
        nu = datetime.now(TZ)
        voorbij = sum(1 for a in met_tijd if a["eind"] <= nu)
        met_tijd = [a for a in met_tijd if a["eind"] > nu]
    if met_tijd:
        nu_bezig = datum == _vandaag() and met_tijd[0]["begin"] <= datetime.now(TZ)
        label = "Nu bezig" if nu_bezig else ("Volgende afspraak" if voorbij else "Eerste afspraak")
        regels.append(f"{label}: {_regel(met_tijd[0])}.")
    if trainingen:
        regels.append("Training: " + "; ".join(trainingen) + ".")
    if hele_dag:
        regels.append("Hele dag: " + "; ".join(f"{a['titel']} ({a['agenda']})" for a in hele_dag) + ".")
    if len(met_tijd) > 1:
        regels.append("Daarna: " + "; ".join(_regel(a) for a in met_tijd[1:]) + ".")
    if not met_tijd and not hele_dag:
        regels.append("Geen afspraken meer vandaag." if voorbij else "Geen afspraken.")
    regels.extend(_herinneringen_regels(datum))
    if fouten:
        regels.append("(" + " ".join(f if f.endswith(".") else f + "." for f in fouten) + ")")
    return "\n".join(regels)
