# MCP server for Indy.gov

Only supports fetching trash pickup day for now.

JSON config (tested with Claude):

```json
{
  "mcpServers": {
    "indy_gov": {
      "command": "uv",
      "args": [
        "--directory",
        "<your_downloaded_location>/indy-gov-mcp/",
        "run",
        "server.py"
      ]
    }
  }
}
```
