import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "evo-fixture", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "selected_component", "description": "Return the selected MCP identity", "inputSchema": {"type": "object"}}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "EVO_MCP_VALUE=23"}]}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
