"""Minimal MCP client: handshake, list a server's tools, call one."""
import json

import httpx

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _jsonrpc(text):
    if text.lstrip().startswith("{"):
        return json.loads(text)
    for line in text.splitlines():  # streamable-http replies as SSE
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return {}


def _session(client, url):
    headers = dict(HEADERS)
    start = client.post(url, headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "awo", "version": "0"}}})
    if start.headers.get("mcp-session-id"):
        headers["Mcp-Session-Id"] = start.headers["mcp-session-id"]
    client.post(url, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    return headers


def call(url, tool, arguments):
    """Run one tool on an MCP server and return its text."""
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        headers = _session(client, url)
        reply = _jsonrpc(client.post(url, headers=headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments}}).text)
    if "error" in reply:
        return f"error: {reply['error']}"
    result = reply.get("result", reply)
    return "\n".join(c.get("text", "") for c in result.get("content", [])) or json.dumps(result)


def connect(url, prefix=""):
    """Every tool a server offers, as ollama tool schemas plus callables to run them."""
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        headers = _session(client, url)
        reply = _jsonrpc(client.post(url, headers=headers, json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}).text)
    if "error" in reply:
        raise RuntimeError(reply["error"])
    schemas, dispatch = [], {}
    for tool in reply.get("result", {}).get("tools", []):
        name = prefix + tool["name"]
        schemas.append({"type": "function", "function": {
            "name": name,
            "description": tool.get("description", "")[:400],
            "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}}}})
        dispatch[name] = (lambda server, real: lambda **kw: call(server, real, kw))(url, tool["name"])
    return schemas, dispatch
