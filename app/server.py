from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
import asyncio
from typing import Any

import jwt
from jwt import InvalidTokenError, PyJWKClient
from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl
from starlette.responses import JSONResponse


MCP_HTTP_HOST = os.environ.get("MCP_HTTP_HOST", "127.0.0.1")
MCP_HTTP_PORT = int(os.environ.get("MCP_HTTP_PORT", "8000"))
MCP_HTTP_PATH = os.environ.get("MCP_HTTP_PATH", "/mcp")


def _env_bool(name: str, default: bool = False) -> bool:
  value = os.environ.get(name)
  if value is None:
    return default
  return value.lower() in ("1", "true", "yes", "on")

def _split_space_or_comma_list(value: str) -> list[str]:
  return [x for x in value.replace(",", " ").split() if x]

MCP_AUTH_ENABLED = _env_bool("MCP_AUTH_ENABLED", False)

COGNITO_REGION = os.environ.get("COGNITO_REGION", "")
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "")
COGNITO_REQUIRED_SCOPES = _split_space_or_comma_list(os.environ.get("COGNITO_REQUIRED_SCOPES", ""))
COGNITO_ALLOWED_USERNAME = os.environ.get("COGNITO_ALLOWED_USERNAME", "")
COGNITO_ALLOWED_SUB = os.environ.get("COGNITO_ALLOWED_SUB", "")
COGNITO_ALLOWED_GROUP = os.environ.get("COGNITO_ALLOWED_GROUP", "")
COGNITO_EXPECTED_AUDIENCE = os.environ.get("COGNITO_EXPECTED_AUDIENCE", "")
JWT_DECODE_ALGORITHMS = _split_space_or_comma_list(os.environ.get("JWT_DECODE_ALGORITHMS", ""))

COGNITO_ISSUER = os.environ.get(
  "COGNITO_ISSUER",
  f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}",
)

COGNITO_JWKS_URL = os.environ.get(
  "COGNITO_JWKS_URL",
  f"{COGNITO_ISSUER}/.well-known/jwks.json",
)

MCP_RESOURCE_SERVER_URL = os.environ.get(
  "MCP_RESOURCE_SERVER_URL",
  f"http://127.0.0.1:{MCP_HTTP_PORT}",
)

MCP_DUMP_TOKEN = _env_bool("MCP_DUMP_TOKEN", False)

class CognitoTokenVerifier(TokenVerifier):
  def __init__(self):
    self._jwks_client = PyJWKClient(COGNITO_JWKS_URL)

  async def verify_token(self, token: str) -> AccessToken | None:
    if MCP_DUMP_TOKEN:
      print("verify_token called", flush=True)

    try:
      payload = await asyncio.to_thread(self._decode_token, token)
    except InvalidTokenError as exc:
      print(f"token verification failed: {type(exc).__name__}", flush=True)
      return None
    except Exception as exc:
      print(f"token verification error: {type(exc).__name__}", flush=True)
      return None

    if MCP_DUMP_TOKEN:
      print(f'{payload=}')

    if payload.get("token_use") != "access":
      return None

    if COGNITO_CLIENT_ID and payload.get("client_id") != COGNITO_CLIENT_ID:
      return None

    if COGNITO_ALLOWED_USERNAME and payload.get("username") != COGNITO_ALLOWED_USERNAME:
      return None

    if COGNITO_ALLOWED_SUB and payload.get("sub") != COGNITO_ALLOWED_SUB:
      return None

    if COGNITO_ALLOWED_GROUP:
      groups = payload.get("cognito:groups") or []
      if COGNITO_ALLOWED_GROUP not in groups:
        return None

    if COGNITO_EXPECTED_AUDIENCE:
      aud = payload.get("aud")
      if isinstance(aud, list):
        if COGNITO_EXPECTED_AUDIENCE not in aud:
          return None
      elif aud != COGNITO_EXPECTED_AUDIENCE:
        return None

    scopes = _split_space_or_comma_list(str(payload.get("scope", "")))
    if not set(COGNITO_REQUIRED_SCOPES).issubset(set(scopes)):
      return None

    return AccessToken(
      token=token,
      client_id=str(payload.get("client_id", "")),
      scopes=scopes,
      expires_at=payload.get("exp"),
      resource=payload.get("aud") if isinstance(payload.get("aud"), str) else None,
      subject=payload.get("sub"),
      claims=payload,
    )

  def _decode_token(self, token: str) -> dict[str, Any]:
    signing_key = self._jwks_client.get_signing_key_from_jwt(token).key
    algorithms = JWT_DECODE_ALGORITHMS
    if not algorithms:
      algorithms = [str(jwt.get_unverified_header(token)["alg"])]

    return jwt.decode(
      token,
      signing_key,
      algorithms=algorithms,
      issuer=COGNITO_ISSUER,
      options={"verify_aud": False},
    )

def _create_auth_settings() -> AuthSettings | None:
  if not MCP_AUTH_ENABLED:
    return None

  if not COGNITO_REGION:
    raise RuntimeError("COGNITO_REGION is required when MCP_AUTH_ENABLED=1")
  if not COGNITO_USER_POOL_ID:
    raise RuntimeError("COGNITO_USER_POOL_ID is required when MCP_AUTH_ENABLED=1")
  if not COGNITO_CLIENT_ID:
    raise RuntimeError("COGNITO_CLIENT_ID is required when MCP_AUTH_ENABLED=1")
  if not COGNITO_REQUIRED_SCOPES:
    raise RuntimeError("COGNITO_REQUIRED_SCOPES is required when MCP_AUTH_ENABLED=1")

  return AuthSettings(
    issuer_url=AnyHttpUrl(COGNITO_ISSUER),
    resource_server_url=AnyHttpUrl(MCP_RESOURCE_SERVER_URL),
    required_scopes=COGNITO_REQUIRED_SCOPES,
  )


auth_settings = _create_auth_settings()
token_verifier = CognitoTokenVerifier() if MCP_AUTH_ENABLED else None

if MCP_AUTH_ENABLED and (token_verifier is None or auth_settings is None):
  raise RuntimeError("MCP authentication is enabled but auth components were not initialized")

mcp = FastMCP(
  "local-files-readonly",
  host=MCP_HTTP_HOST,
  port=MCP_HTTP_PORT,
  streamable_http_path=MCP_HTTP_PATH,
  stateless_http=True,
  json_response=True,
  token_verifier=token_verifier,
  auth=auth_settings,
)


ROOT = Path(os.environ.get("MCP_ROOT", "/workspace")).resolve()
MAX_READ_BYTES = int(os.environ.get("MAX_READ_BYTES", "262144"))
MAX_SCAN_BYTES = int(os.environ.get("MAX_SCAN_BYTES", "1048576"))
MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "100"))

DEFAULT_ALLOW_EXTS = """
.py,.pyi,.rs,.c,.cc,.cpp,.cxx,.h,.hh,.hpp,.hxx,
.cs,.java,.kt,.kts,.go,.js,.jsx,.ts,.tsx,.mjs,.cjs,
.el,.lua,.rb,.php,.swift,.m,.mm,
.md,.txt,.rst,.adoc,
.json,.jsonc,.yaml,.yml,.toml,.ini,.cfg,.conf,.xml,
.sql,.sh,.bash,.zsh,.ps1,.bat,.cmd,
.uplugin,.uproject,.build.cs,.target.cs
"""

def _split_env_list(value: str) -> set[str]:
  return {x.strip().lower() for x in value.replace("\n", ",").split(",") if x.strip()}

ALLOW_EXTS = _split_env_list(os.environ.get("ALLOW_EXTS", DEFAULT_ALLOW_EXTS))

SKIP_DIRS = {
  ".git", ".hg", ".svn",
  "node_modules", ".venv", "venv", "__pycache__",
  ".mypy_cache", ".pytest_cache", ".ruff_cache",
  "target", "dist", "build", ".next", ".turbo",
}

DENY_NAMES = {
  ".env", ".env.local", ".env.production",
  ".npmrc", ".pypirc", ".netrc",
  "id_rsa", "id_ed25519", "id_dsa", "id_ecdsa",
  "known_hosts",
}

DENY_EXTS = {
  ".pem", ".key", ".p12", ".pfx", ".kdbx", ".age",
  ".sqlite", ".db", ".mdb",
}

ALLOW_NAMES = {
  "Dockerfile", "Makefile", "CMakeLists.txt", "LICENSE",
}

FALLBACK_ENCODING_EXTS = {".bat", ".cmd"}

def _parts(path: str) -> tuple[str, ...]:
  normalized = (path or "").replace("\\", "/")
  if normalized.startswith("/"):
    raise ValueError("absolute paths are not allowed")

  parts = tuple(x for x in normalized.split("/") if x not in ("", "."))
  if any(x == ".." for x in parts):
    raise ValueError("parent-directory traversal is not allowed")
  return parts

def _safe_path(path: str) -> Path:
  cur = ROOT
  for part in _parts(path):
    cur = cur / part
    if cur.is_symlink():
      raise ValueError("symlinks are not followed")

  resolved = cur.resolve(strict=False)
  if resolved != ROOT and ROOT not in resolved.parents:
    raise ValueError("path escapes workspace")
  return resolved

def _rel(path: Path) -> str:
  if path == ROOT:
    return "."
  return path.relative_to(ROOT).as_posix()

def _is_skipped_dir(path: Path) -> bool:
  return path.name in SKIP_DIRS or path.is_symlink()

def _is_denied_file(path: Path) -> bool:
  if path.name in DENY_NAMES:
    return True
  if path.suffix.lower() in DENY_EXTS:
    return True
  if path.name not in ALLOW_NAMES and path.suffix.lower() not in ALLOW_EXTS:
    return True
  return False

def _text_encodings(path: Path) -> tuple[str, ...]:
  if path.suffix.lower() in FALLBACK_ENCODING_EXTS:
    return ("utf-8", "cp932")
  return ("utf-8",)

def _decode_text(path: Path, data: bytes) -> str:
  for encoding in _text_encodings(path):
    try:
      return data.decode(encoding)
    except UnicodeDecodeError:
      continue
  raise UnicodeDecodeError("utf-8", data, 0, 1, "file is not valid text")

def _is_probably_text(path: Path, max_bytes: int) -> bool:
  if not path.is_file():
    return False
  if _is_denied_file(path):
    return False
  if path.stat().st_size > max_bytes:
    return False

  data = path.read_bytes()
  if b"\x00" in data:
    return False
  try:
    _decode_text(path, data)
  except UnicodeDecodeError:
    return False
  return True

def _read_text_file(path: Path) -> str:
  return _decode_text(path, path.read_bytes())

def _walk_files(base: Path):
  if base.is_file():
    yield base
    return

  for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
    current = Path(dirpath)

    dirnames[:] = [
      name for name in dirnames
      if not _is_skipped_dir(current / name)
    ]

    for name in filenames:
      path = current / name
      if path.is_symlink():
        continue
      yield path

@mcp.tool()
def list_files(path: str = "", recursive: bool = False, max_entries: int = 200) -> list[dict[str, Any]]:
  """List files and directories under the workspace. This tool is read-only."""
  base = _safe_path(path)
  if not base.exists():
    raise ValueError("path does not exist")
  if not base.is_dir():
    raise ValueError("path is not a directory")

  max_entries = max(1, min(max_entries, 1000))
  entries: list[dict[str, Any]] = []

  if recursive:
    for child in _walk_files(base):
      if len(entries) >= max_entries:
        break
      if _is_denied_file(child):
        continue
      entries.append({
        "path": _rel(child),
        "type": "file",
        "size": child.stat().st_size,
      })
  else:
    for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
      if len(entries) >= max_entries:
        break
      if child.is_symlink():
        continue
      if child.is_dir():
        if _is_skipped_dir(child):
          continue
        entries.append({
          "path": _rel(child),
          "type": "dir",
        })
      elif child.is_file() and not _is_denied_file(child):
        entries.append({
          "path": _rel(child),
          "type": "file",
          "size": child.stat().st_size,
        })

  return entries

@mcp.tool()
def find_files(pattern: str, path: str = "", max_results: int = 100) -> list[str]:
  """Find files by shell-style wildcard pattern under the workspace. This tool is read-only."""
  if not pattern:
    raise ValueError("pattern is required")

  base = _safe_path(path)
  max_results = max(1, min(max_results, MAX_RESULTS))
  matches: list[str] = []

  for file_path in _walk_files(base):
    if _is_denied_file(file_path):
      continue
    rel = _rel(file_path)
    if fnmatch.fnmatch(file_path.name, pattern) or fnmatch.fnmatch(rel, pattern):
      matches.append(rel)
      if len(matches) >= max_results:
        break

  return matches

@mcp.tool()
def read_file(path: str, start_line: int = 1, max_lines: int = 400) -> dict[str, Any]:
  """Read a text file from the workspace. This tool is read-only."""
  file_path = _safe_path(path)
  if not _is_probably_text(file_path, MAX_READ_BYTES):
    raise ValueError("file is not allowed, is too large, or is not supported text")

  start_line = max(1, start_line)
  max_lines = max(1, min(max_lines, 2000))

  selected: list[str] = []
  end_line = start_line - 1

  for line_no, line in enumerate(_read_text_file(file_path).splitlines(), start=1):
    if line_no < start_line:
      continue
    if len(selected) >= max_lines:
      break
    selected.append(line)
    end_line = line_no

  return {
    "path": _rel(file_path),
    "start_line": start_line,
    "end_line": end_line,
    "text": "\n".join(selected),
  }

@mcp.tool()
def search_text(
  query: str,
  path: str = "",
  regex: bool = False,
  case_sensitive: bool = False,
  max_results: int = 100,
) -> list[dict[str, Any]]:
  """Search text files under the workspace. This tool is read-only."""
  if not query:
    raise ValueError("query is required")

  base = _safe_path(path)
  max_results = max(1, min(max_results, MAX_RESULTS))
  flags = 0 if case_sensitive else re.IGNORECASE
  pattern = re.compile(query if regex else re.escape(query), flags)

  results: list[dict[str, Any]] = []

  for file_path in _walk_files(base):
    if not _is_probably_text(file_path, MAX_SCAN_BYTES):
      continue

    for line_no, line in enumerate(_read_text_file(file_path).splitlines(), start=1):
      if pattern.search(line):
        results.append({
          "path": _rel(file_path),
          "line": line_no,
          "text": line[:500],
        })
        if len(results) >= max_results:
          return results

  return results


@mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
async def healthz(request):
  return JSONResponse({"status": "ok"})


if __name__ == "__main__":
  mcp.run(transport="streamable-http")
