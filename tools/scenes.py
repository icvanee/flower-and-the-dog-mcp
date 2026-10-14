"""
HomeKit-scènes via Opdrachten (Shortcuts) op de Mini.

Een scène is een opdracht waarvan de naam begint met "Scene " (of "Scène "),
bijvoorbeeld "Scene thuiskomen". Alleen die opdrachten kunnen hier worden
uitgevoerd: dat is een harde veiligheidsgrens, zodat de connector nooit een
willekeurige andere opdracht start. De lijst wordt tien minuten gecachet.
"""

import asyncio
import difflib
import subprocess
import time
import unicodedata

PREFIXEN = ("scene ", "scène ")
CACHE_SECONDEN = 600
TIMEOUT_SECONDEN = 20

_scenes: dict[str, str] = {}  # genormaliseerde naam zonder prefix -> exacte opdrachtnaam
_scenes_at = 0.0


def _norm(tekst: str) -> str:
    zonder_accent = "".join(c for c in unicodedata.normalize("NFKD", tekst) if not unicodedata.combining(c))
    return " ".join(zonder_accent.lower().split())


def _weergave(opdracht: str) -> str:
    naam = opdracht.split(" ", 1)[1].strip()
    return naam[:1].upper() + naam[1:]


def _lijst() -> dict[str, str]:
    global _scenes, _scenes_at
    if _scenes and time.monotonic() - _scenes_at < CACHE_SECONDEN:
        return _scenes
    p = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=TIMEOUT_SECONDEN)
    if p.returncode != 0:
        raise RuntimeError("Opdrachten kon de lijst niet geven.")
    _scenes = {_norm(_weergave(o)): o for o in p.stdout.splitlines()
               if any(_norm(o).startswith(_norm(prefix)) for prefix in PREFIXEN) and len(o.split(" ", 1)) == 2}
    _scenes_at = time.monotonic()
    return _scenes


def _namen(scenes: dict[str, str]) -> str:
    return ", ".join(sorted(_weergave(o) for o in scenes.values())) or "geen"


def _zoek(naam: str, scenes: dict[str, str]) -> str | None:
    """Exacte opdrachtnaam bij een gesproken naam, met wat speling voor spraakherkenning."""
    n = _norm(naam)
    for prefix in PREFIXEN:  # "scène thuiskomen" mag ook
        if n.startswith(_norm(prefix)):
            n = n[len(_norm(prefix)):]
    if n in scenes:
        return scenes[n]
    dichtbij = difflib.get_close_matches(n, scenes.keys(), n=1, cutoff=0.75)
    return scenes[dichtbij[0]] if dichtbij else None


def _scenes_sync() -> str:
    scenes = _lijst()
    if not scenes:
        return "Er zijn geen scènes. Een scène is een opdracht in Opdrachten die begint met 'Scene '."
    return f"Scènes: {_namen(scenes)}."


def _scene_sync(naam: str, bevestigd: bool) -> str:
    scenes = _lijst()
    opdracht = _zoek(naam, scenes)
    if opdracht is None:
        return f"Scène '{naam}' ken ik niet. Beschikbaar: {_namen(scenes)}."
    weergave = _weergave(opdracht)
    if not bevestigd:
        return (f"Nog niet uitgevoerd. Vraag: zal ik de scène {weergave} aanzetten? "
                "Roep na een duidelijk ja opnieuw aan met bevestigd=true.")
    # Veiligheidsgrens: alleen een opdracht uit de scènelijst, nooit iets anders
    if opdracht not in scenes.values() or not any(_norm(opdracht).startswith(_norm(x)) for x in PREFIXEN):
        return "Dat is geen scène, ik voer het niet uit."
    try:
        p = subprocess.run(["shortcuts", "run", opdracht], capture_output=True, text=True, timeout=TIMEOUT_SECONDEN)
    except subprocess.TimeoutExpired:
        return f"De scène {weergave} reageerde niet binnen {TIMEOUT_SECONDEN} seconden."
    if p.returncode != 0:
        return f"De scène {weergave} kon niet worden uitgevoerd."
    return f"Scène {weergave} staat aan."


async def scenes() -> str:
    try:
        return await asyncio.to_thread(_scenes_sync)
    except (RuntimeError, subprocess.TimeoutExpired):
        return "Opdrachten reageert niet, de scènes zijn nu niet beschikbaar."


async def scene(naam: str, bevestigd: bool = False) -> str:
    try:
        return await asyncio.to_thread(_scene_sync, naam, bevestigd)
    except (RuntimeError, subprocess.TimeoutExpired):
        return "Opdrachten reageert niet, er is niets uitgevoerd."
