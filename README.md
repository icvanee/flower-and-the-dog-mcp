# Flower and the Dog — MCP Toolbox

Personal MCP server with SSE transport. Deployed on Railway.

## Tools

| Tool | Description |
|------|-------------|
| `get_current_datetime` | Current date/time in Amsterdam timezone |
| `calculate` | Evaluate a math expression |
| `coachleo_get_plan` | Get training plan from Coach Leo |
| `coachleo_get_upcoming_races` | Get upcoming races |
| `coachleo_log_run` | Log a completed run |

## Environment variables

| Variable | Description |
|----------|-------------|
| `MCP_SECRET_TOKEN` | Bearer token for authentication |
| `COACHLEO_BASE_URL` | Base URL of Coach Leo API |
| `COACHLEO_API_KEY` | Coach Leo API key / JWT |
| `PORT` | Port (Railway sets this automatically) |

## Client configuration

### Claude Desktop
```json
{
  "mcpServers": {
    "flower-and-the-dog": {
      "type": "sse",
      "url": "https://mcp.flowerandthedog.nl/sse",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

### VS Code / Continue
```json
{
  "mcpServers": [
    {
      "name": "flower-and-the-dog",
      "transport": {
        "type": "sse",
        "url": "https://mcp.flowerandthedog.nl/sse",
        "requestInit": {
          "headers": {
            "Authorization": "Bearer YOUR_TOKEN"
          }
        }
      }
    }
  ]
}
```
