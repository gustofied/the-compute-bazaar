"""Small MCP surface for actions in the visible Terminal."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from .lifecycle import open_terminal_workspace

PROTOCOL_VERSION = "2025-06-18"
WORKSPACES = ("home", "data", "fleet", "eval")
OPEN_WORKSPACE_TOOL = {
    "name": "open_workspace",
    "title": "Open Terminal workspace",
    "description": "Open Home, Data, Fleet, or Eval in the visible Compute Bazaar Terminal.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "workspace": {
                "type": "string",
                "enum": list(WORKSPACES),
            }
        },
        "required": ["workspace"],
        "additionalProperties": False,
    },
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
}


def handle_request(
    request: dict[str, Any],
    *,
    opener: Callable[[str], str] = open_terminal_workspace,
) -> dict[str, Any] | None:
    """Handle one JSON-RPC request from the ACP client."""
    method = request.get("method")
    request_id = request.get("id")
    if request_id is None:
        return None
    if method == "initialize":
        params = request.get("params")
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        return _result(
            request_id,
            {
                "protocolVersion": requested or PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "compute-bazaar-terminal", "version": "1"},
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": [OPEN_WORKSPACE_TOOL]})
    if method == "tools/call":
        return _call_tool(request_id, request.get("params"), opener=opener)
    if method in {"prompts/list", "resources/list", "resources/templates/list"}:
        key = "prompts" if method == "prompts/list" else "resources"
        if method == "resources/templates/list":
            key = "resourceTemplates"
        return _result(request_id, {key: []})
    return _error(request_id, -32601, f"Method not found: {method}")


def _call_tool(
    request_id: Any,
    params: Any,
    *,
    opener: Callable[[str], str],
) -> dict[str, Any]:
    if not isinstance(params, dict) or params.get("name") != "open_workspace":
        return _error(request_id, -32602, "Unknown tool")
    arguments = params.get("arguments")
    workspace = arguments.get("workspace") if isinstance(arguments, dict) else None
    if workspace not in WORKSPACES:
        return _error(request_id, -32602, "workspace must be home, data, fleet, or eval")
    try:
        message = opener(workspace)
    except Exception as exc:
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            },
        )
    return _result(
        request_id,
        {
            "content": [{"type": "text", "text": message}],
            "structuredContent": {"workspace": workspace, "opened": True},
            "isError": False,
        },
    )


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def main() -> None:
    """Serve newline-delimited MCP over stdin/stdout."""
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = handle_request(request) if isinstance(request, dict) else None
        except Exception as exc:
            response = _error(None, -32700, str(exc))
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
