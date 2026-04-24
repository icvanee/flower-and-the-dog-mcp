"""
Coach Leo integration tools.

Set these environment variables in Railway:
  COACHLEO_BASE_URL   e.g. https://coachleo.up.railway.app
  COACHLEO_API_KEY    your API key or JWT token
"""

import os
import httpx
from datetime import datetime, timedelta


def _client() -> httpx.AsyncClient:
    base_url = os.environ.get("COACHLEO_BASE_URL", "")
    api_key = os.environ.get("COACHLEO_API_KEY", "")
    return httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15.0,
    )


async def coachleo_get_plan(week_offset: int = 0) -> dict:
    """
    Fetch the training plan for a given week.
    Replace the endpoint path once Coach Leo exposes it.
    """
    target_date = datetime.now() + timedelta(weeks=week_offset)
    week_str = target_date.strftime("%Y-%W")

    # ── TODO: update endpoint when Coach Leo API is ready ──
    # async with _client() as c:
    #     r = await c.get("/api/training-plan", params={"week": week_str})
    #     r.raise_for_status()
    #     return r.json()

    return {
        "status": "placeholder",
        "message": "Coach Leo API not yet connected. Update COACHLEO_BASE_URL and endpoint in tools/coachleo.py",
        "week": week_str,
        "week_offset": week_offset,
    }


async def coachleo_get_upcoming_races() -> dict:
    """
    Fetch upcoming races from Coach Leo.
    """
    # ── TODO: update endpoint when Coach Leo API is ready ──
    # async with _client() as c:
    #     r = await c.get("/api/races", params={"upcoming": True})
    #     r.raise_for_status()
    #     return r.json()

    return {
        "status": "placeholder",
        "message": "Coach Leo API not yet connected. Update endpoint in tools/coachleo.py",
    }


async def coachleo_log_run(
    distance_km: float,
    duration_minutes: float,
    notes: str = "",
) -> dict:
    """
    Log a completed run.
    """
    pace_per_km = duration_minutes / distance_km if distance_km > 0 else 0
    payload = {
        "distance_km": distance_km,
        "duration_minutes": duration_minutes,
        "notes": notes,
        "logged_at": datetime.now().isoformat(),
        "pace_min_per_km": round(pace_per_km, 2),
    }

    # ── TODO: update endpoint when Coach Leo API is ready ──
    # async with _client() as c:
    #     r = await c.post("/api/activities", json=payload)
    #     r.raise_for_status()
    #     return r.json()

    return {
        "status": "placeholder",
        "message": "Coach Leo API not yet connected. Update endpoint in tools/coachleo.py",
        "payload_that_would_be_sent": payload,
    }
