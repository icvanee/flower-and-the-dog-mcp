import asyncio
import os
import json
from datetime import datetime

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn

from tools.coachleo import (
    coachleo_get_plan,
    coachleo_get_upcoming_races,
    coachleo_log_run,
)
from tools.carwash import carwash_get_history

server = Server("flower-and-the-dog-toolbox")

# ─── Auth middleware ───────────────────────────────────────────────────────────

class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Health checks always allowed
        if request.url.path in ["/health", "/"]:
            return await call_next(request)
        # /messages is protected by session_id (only given to auth'd clients via /sse)
        if request.url.path.startswith("/messages") and request.query_params.get("session_id"):
            return await call_next(request)
        # All other endpoints require Bearer token
        token = request.headers.get("Authorization", "")
        expected = f"Bearer {os.environ.get('MCP_SECRET_TOKEN', '')}"
        if token != expected:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)

# ─── Tool definitions ──────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # General tools
        Tool(
            name="get_current_datetime",
            description="Returns the current date and time in Amsterdam timezone",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="calculate",
            description="Evaluates a simple math expression. E.g. '12 * 8.5' or '(100 - 21) * 1.21'",
            inputSchema={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression to evaluate"}
                },
                "required": ["expression"],
            },
        ),

        # Carwash tool
        Tool(
            name="carwash_get_history",
            description="Geeft de wasgeschiedenis van de auto terug via het Carwash Kleiboer klantenportaal. Gebruik dit om te vragen wanneer de auto voor het laatst gewassen is.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Hoeveel dagen terug te kijken (standaard 365).",
                    }
                },
                "required": [],
            },
        ),

        # Coach Leo tools
        Tool(
            name="coachleo_get_plan",
            description="Get the training plan from Coach Leo for a given week",
            inputSchema={
                "type": "object",
                "properties": {
                    "week_offset": {
                        "type": "integer",
                        "description": "0 = current week, 1 = next week, -1 = last week. Default 0.",
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="coachleo_get_upcoming_races",
            description="Get upcoming races from Coach Leo",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="coachleo_log_run",
            description="Log a completed run in Coach Leo",
            inputSchema={
                "type": "object",
                "properties": {
                    "distance_km": {"type": "number", "description": "Distance in kilometers"},
                    "duration_minutes": {"type": "number", "description": "Duration in minutes"},
                    "notes": {"type": "string", "description": "Optional notes about the run"},
                },
                "required": ["distance_km", "duration_minutes"],
            },
        ),
    ]

# ─── Tool implementations ──────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:

    if name == "carwash_get_history":
        days = arguments.get("days", 365)
        result = await carwash_get_history(days=days)
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    elif name == "get_current_datetime":
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Europe/Amsterdam"))
        result = {
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "weekday": now.strftime("%A"),
            "timezone": "Europe/Amsterdam",
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "calculate":
        expression = arguments.get("expression", "")
        # Safe eval — only allow numbers and operators
        allowed = set("0123456789+-*/(). ")
        if not all(c in allowed for c in expression):
            return [TextContent(type="text", text=json.dumps({"error": "Invalid characters in expression"}))]
        try:
            result = eval(expression, {"__builtins__": {}}, {})
            return [TextContent(type="text", text=json.dumps({"expression": expression, "result": result}))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    elif name == "coachleo_get_plan":
        week_offset = arguments.get("week_offset", 0)
        result = await coachleo_get_plan(week_offset)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "coachleo_get_upcoming_races":
        result = await coachleo_get_upcoming_races()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "coachleo_log_run":
        result = await coachleo_log_run(
            distance_km=arguments["distance_km"],
            duration_minutes=arguments["duration_minutes"],
            notes=arguments.get("notes", ""),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    else:
        raise ValueError(f"Unknown tool: {name}")

# ─── SSE transport ─────────────────────────────────────────────────────────────

sse = SseServerTransport("/messages")

async def handle_sse(request):
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await server.run(
            streams[0], streams[1], server.create_initialization_options()
        )

async def health(request):
    return JSONResponse({"status": "ok", "server": "flower-and-the-dog-toolbox"})

app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages", app=sse.handle_post_message),
        Route("/health", endpoint=health),
        Route("/", endpoint=health),
    ],
    middleware=[Middleware(BearerAuthMiddleware)],
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
