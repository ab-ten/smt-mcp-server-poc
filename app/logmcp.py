import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP


ACCESS_LOGGER = logging.getLogger("mcp.access")
ACCESS_LOG_STRING_LIMIT = 500
ACCESS_LOG_SEQUENCE_LIMIT = 50

SENSITIVE_LOG_KEYS = frozenset({
  "authorization",
  "access_token",
  "api_key",
  "apikey",
  "password",
  "secret",
  "token",
})


def _sanitize_log_value(value: Any, key: str = "") -> Any:
  """ログ出力用に値を制限・秘匿します。"""
  if key.casefold() in SENSITIVE_LOG_KEYS:
    return "<redacted>"

  if value is None or isinstance(value, (bool, int, float)):
    return value

  if isinstance(value, str):
    if len(value) <= ACCESS_LOG_STRING_LIMIT:
      return value
    return f"{value[:ACCESS_LOG_STRING_LIMIT]}...<{len(value)} chars>"

  if isinstance(value, Mapping):
    return {
      str(child_key): _sanitize_log_value(child_value, str(child_key))
      for child_key, child_value in value.items()
    }

  if isinstance(value, (list, tuple)):
    values = [
      _sanitize_log_value(child_value)
      for child_value in value[:ACCESS_LOG_SEQUENCE_LIMIT]
    ]
    if len(value) > ACCESS_LOG_SEQUENCE_LIMIT:
      values.append(f"<{len(value)-ACCESS_LOG_SEQUENCE_LIMIT} more items>")
    return values

  return _sanitize_log_value(repr(value))


class AccessLogFastMCP(FastMCP):
  """すべての MCP ツール呼び出しをアクセスログへ記録します。"""

  async def call_tool(
    self,
    name: str,
    arguments: dict[str, Any],
  ) -> Any:
    started_at = time.perf_counter()
    context = self.get_context()
    access_token = get_access_token()

    event: dict[str, Any] = {
      "event": "mcp_tool_call",
      "tool": name,
      "request_id": context.request_id,
      "mcp_client_id": context.client_id,
      "arguments": _sanitize_log_value(arguments),
    }

    if access_token is not None:
      event["oauth_client_id"] = access_token.client_id

    try:
      result = await super().call_tool(name, arguments)
    except Exception as exc:
      event["status"] = "error"
      event["error_type"] = type(exc).__name__
      raise
    else:
      event["status"] = "ok"
      event["result_type"] = type(result).__name__
      return result
    finally:
      event["duration_ms"] = round(
        (time.perf_counter()-started_at)*1000,
        3,
      )
      ACCESS_LOGGER.info(
        "%s",
        json.dumps(
          event,
          ensure_ascii=False,
          separators=(",", ":"),
        ),
      )
