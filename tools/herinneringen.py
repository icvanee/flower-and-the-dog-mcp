"""
Apple Herinneringen via de Herinneringen-app op de Mini (AppleScript).

Herinneringen zitten niet meer in CalDAV (ze staan in CloudKit), dus dit loopt via
osascript. De app moet draaien; anders geeft AppleScript fout -609 en starten we
hem eerst op de achtergrond. De eerste aanroep vanuit launchd vraagt op het scherm
van de Mini om toestemming (Automatisering → Herinneringen).

Waarden gaan als argumenten naar het script (`on run argv`), nooit in de
scripttekst zelf, zodat een titel met aanhalingstekens niets kan breken.
Alleen toevoegen; verwijderen of wijzigen kan niet.
"""

import asyncio
import subprocess
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from tools.agenda import _dag, _parse_datum, _parse_tijd

TZ = ZoneInfo("Europe/Amsterdam")
STANDAARD_LIJST = "Herinneringen"  # niet "Family ⚠️": die is gedeeld met het gezin

LIJSTEN_SCRIPT = 'tell application "Reminders" to get name of every list'

# argv: lijst, titel, notitie, soort ("geen" | "dag" | "tijd"), jaar, maand, dag, uur, minuut
MAAK_SCRIPT = """
on run argv
  set {lijstNaam, titel, notitie, soort} to items 1 thru 4 of argv
  tell application "Reminders"
    set props to {name:titel}
    if notitie is not "" then set props to props & {body:notitie}
    set r to make new reminder at end of reminders of list lijstNaam with properties props
    if soort is not "geen" then
      set d to current date
      set day of d to 1
      set year of d to (item 5 of argv) as integer
      set month of d to (item 6 of argv) as integer
      set day of d to (item 7 of argv) as integer
      set time of d to ((item 8 of argv) as integer) * hours + ((item 9 of argv) as integer) * minutes
      if soort is "dag" then
        set allday due date of r to d
      else
        set due date of r to d
        set remind me date of r to d
      end if
    end if
    return id of r
  end tell
end run
"""


def _osascript(script: str, *args: str) -> str:
    for poging in range(2):
        p = subprocess.run(["osascript", "-e", script, *args], capture_output=True, text=True, timeout=30)
        if p.returncode == 0:
            return p.stdout.strip()
        if "-609" in p.stderr and poging == 0:
            # De app draait niet: op de achtergrond starten en nog eens proberen
            subprocess.run(["open", "-g", "-a", "Reminders"], timeout=15)
            subprocess.run(["sleep", "2"])
            continue
        if "-1743" in p.stderr:
            raise RuntimeError("Geen toestemming voor Herinneringen. Sta die toe op het scherm van de Mac Mini "
                               "(Systeeminstellingen → Privacy en beveiliging → Automatisering).")
        raise RuntimeError(f"Herinneringen gaf een fout: {p.stderr.strip()}")
    raise RuntimeError("Herinneringen reageert niet.")


def _norm(naam: str) -> str:
    # Kleine letters, rechte apostrof (L’Estartit), zonder ⚠️ en spaties aan de randen
    n = unicodedata.normalize("NFC", naam).replace("’", "'").replace("⚠️", "").replace("⚠", "")
    return n.strip().lower()


def _lijsten() -> list[str]:
    return [l.strip() for l in _osascript(LIJSTEN_SCRIPT).split(", ") if l.strip()]


def _maken_sync(titel: str, datum: str | None, tijd: str | None, lijst: str, notitie: str | None,
                bevestigd: bool) -> str:
    titel = titel.strip()
    if not titel:
        return "Geen titel opgegeven, niets opgeslagen."

    lijsten = _lijsten()
    gevonden = [l for l in lijsten if _norm(l) == _norm(lijst)]
    if not gevonden:
        return f"Lijst '{lijst}' bestaat niet. Kies uit: {', '.join(lijsten)}."
    lijstnaam = gevonden[0]

    if tijd and not datum:
        datum = "vandaag"
    wanneer, soort, delen = "zonder datum", "geen", ["0"] * 5
    if datum:
        dag = _parse_datum(datum)
        if tijd:
            h, m = _parse_tijd(tijd)
            moment = datetime(dag.year, dag.month, dag.day, h, m, tzinfo=TZ)
            if moment < datetime.now(TZ):
                return f"Niets opgeslagen: {_dag(dag)} {h:02d}:{m:02d} ligt in het verleden."
            wanneer, soort = f"op {_dag(dag)} om {h:02d}:{m:02d}, met melding", "tijd"
        else:
            h = m = 0
            wanneer, soort = f"op {_dag(dag)}, zonder tijd", "dag"
        delen = [str(dag.year), str(dag.month), str(dag.day), str(h), str(m)]

    samenvatting = f"herinnering '{titel}' {wanneer}, in de lijst {lijstnaam}"
    if notitie:
        samenvatting += f", met notitie: {notitie.strip()}"
    if not bevestigd:
        return (f"Nog niet opgeslagen. Lees dit voor en vraag om een duidelijk ja: {samenvatting}. "
                "Roep daarna opnieuw aan met bevestigd=true.")

    _osascript(MAAK_SCRIPT, lijstnaam, titel, (notitie or "").strip(), soort, *delen)
    return f"Opgeslagen: {samenvatting}."


async def herinnering_maken(titel: str, datum: str | None = None, tijd: str | None = None,
                            lijst: str = STANDAARD_LIJST, notitie: str | None = None,
                            bevestigd: bool = False) -> str:
    try:
        return await asyncio.to_thread(_maken_sync, titel, datum, tijd, lijst, notitie, bevestigd)
    except (ValueError, RuntimeError) as e:
        return f"Niets opgeslagen. {e}"
