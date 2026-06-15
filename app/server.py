from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any

from pathspec import PathSpec
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

from auth import auth_settings, token_verifier


MCP_HTTP_HOST = os.environ.get("MCP_HTTP_HOST", "127.0.0.1")
MCP_HTTP_PORT = int(os.environ.get("MCP_HTTP_PORT", "8000"))
MCP_HTTP_PATH = os.environ.get("MCP_HTTP_PATH", "/mcp")


def _env_bool(name: str, default: bool = False) -> bool:
  """環境変数の値を真偽値として解釈します。"""
  value = os.environ.get(name)
  if value is None:
    return default
  return value.lower() in ("1", "true", "yes", "on")


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
MCP_IGNORE_NAME = ".mcpignore"

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
  """カンマ区切りまたは改行区切りの環境変数値を小文字の集合に変換します。"""
  return {x.strip().lower() for x in value.replace("\n", ",").split(",") if x.strip()}

ALLOW_EXTS = _split_env_list(os.environ.get("ALLOW_EXTS", DEFAULT_ALLOW_EXTS))
DENY_NAMES_IGNORECASE = _env_bool("DENY_NAMES_IGNORECASE", True)

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
  "known_hosts", MCP_IGNORE_NAME,
}

DENY_NAMES_NORMALIZED = {name.casefold() for name in DENY_NAMES}

DENY_EXTS = {
  ".pem", ".key", ".p12", ".pfx", ".kdbx", ".age",
  ".sqlite", ".db", ".mdb",
}

ALLOW_NAMES = {
  "Dockerfile", "Makefile", "CMakeLists.txt", "LICENSE",
}

FALLBACK_ENCODING_EXTS = {".bat", ".cmd"}

def _parts(path: str) -> tuple[str, ...]:
  """ユーザー指定パスを安全な相対パス部品へ分解します。"""
  normalized = (path or "").replace("\\", "/")
  if normalized.startswith("/"):
    raise ValueError("absolute paths are not allowed")

  parts = tuple(x for x in normalized.split("/") if x not in ("", "."))
  if any(x == ".." for x in parts):
    raise ValueError("parent-directory traversal is not allowed")
  return parts

def _safe_path(path: str) -> Path:
  """ワークスペース外へ出ない安全な絶対パスを返します。"""
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
  """ワークスペースルートからの相対パス文字列を返します。"""
  if path == ROOT:
    return "."
  return path.relative_to(ROOT).as_posix()

def _ancestor_dirs_from_root(path: Path) -> list[Path]:
  """ワークスペースルートから指定ディレクトリまでの祖先ディレクトリを返します。"""
  if path == ROOT:
    return [ROOT]

  dirs = [ROOT]
  cur = ROOT
  for part in path.relative_to(ROOT).parts:
    cur = cur / part
    dirs.append(cur)
  return dirs

def _mcpignore_dirs_for(path: Path) -> list[Path]:
  """指定パスに適用される可能性がある .mcpignore の配置ディレクトリを返します。"""
  return _ancestor_dirs_from_root(path.parent)

def _is_ignored_by_mcpignore(path: Path, is_dir: bool) -> bool:
  """階層ごとの .mcpignore により指定パスが除外されるか判定します。"""
  if path == ROOT:
    return False

  ignored = False
  for ignore_dir in _mcpignore_dirs_for(path):
    ignore_file = ignore_dir / MCP_IGNORE_NAME
    if not ignore_file.is_file() or ignore_file.is_symlink():
      continue

    lines = ignore_file.read_text(encoding="utf-8").splitlines()
    spec = PathSpec.from_lines("gitwildmatch", lines)
    rel = path.relative_to(ignore_dir).as_posix()
    candidates = [rel]
    if is_dir:
      candidates.append(f"{rel}/")

    if any(spec.match_file(candidate) for candidate in candidates):
      ignored = True
    elif any(
      pattern.include is False and pattern.match_file(candidate)
      for pattern in spec.patterns
      for candidate in candidates
    ):
      ignored = False

  return ignored

def _is_skipped_dir(path: Path) -> bool:
  """走査対象から除外するディレクトリかどうかを判定します。"""
  return (
    path.name in SKIP_DIRS
    or path.is_symlink()
    or _is_ignored_by_mcpignore(path, is_dir=True)
  )

def _is_denied_name(name: str) -> bool:
  """拒否対象のファイル名に一致するか判定します。"""
  if DENY_NAMES_IGNORECASE:
    return name.casefold() in DENY_NAMES_NORMALIZED
  return name in DENY_NAMES

def _is_denied_file(path: Path) -> bool:
  """読み取りまたは公開対象から除外するファイルかどうかを判定します。"""
  if _is_ignored_by_mcpignore(path, is_dir=False):
    return True
  if _is_denied_name(path.name):
    return True
  if path.suffix.lower() in DENY_EXTS:
    return True
  if path.name not in ALLOW_NAMES and path.suffix.lower() not in ALLOW_EXTS:
    return True
  return False

def _text_encodings(path: Path) -> tuple[str, ...]:
  """ファイル拡張子に応じて試行するテキストエンコーディングを返します。"""
  if path.suffix.lower() in FALLBACK_ENCODING_EXTS:
    return ("utf-8", "cp932")
  return ("utf-8",)

def _decode_text(path: Path, data: bytes) -> str:
  """許可されたエンコーディングでバイト列をテキストへ変換します。"""
  for encoding in _text_encodings(path):
    try:
      return data.decode(encoding)
    except UnicodeDecodeError:
      continue
  raise UnicodeDecodeError("utf-8", data, 0, 1, "file is not valid text")

def _is_probably_text(path: Path, max_bytes: int) -> bool:
  """ファイルが許可されたサイズ内のテキストとして扱えるか判定します。"""
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
  """ファイル全体をテキストとして読み込みます。"""
  return _decode_text(path, path.read_bytes())

def _walk_files(base: Path):
  """指定パス配下の走査可能なファイルを再帰的に列挙します。"""
  if base.is_file():
    yield base
    return
  if base != ROOT and _is_skipped_dir(base):
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
  """ワークスペース配下のファイルとディレクトリを一覧表示します。"""
  base = _safe_path(path)
  if not base.exists():
    raise ValueError("path does not exist")
  if not base.is_dir():
    raise ValueError("path is not a directory")
  if base != ROOT and _is_skipped_dir(base):
    raise ValueError("path is not allowed")

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
  """シェル形式のワイルドカードでファイルを検索します。"""
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
  """ワークスペース内のテキストファイルを行単位で読み取ります。"""
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
  """ワークスペース内のテキストファイルから文字列または正規表現を検索します。"""
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
  """ヘルスチェック用の JSON レスポンスを返します。"""
  return JSONResponse({"status": "ok"})


if __name__ == "__main__":
  mcp.run(transport="streamable-http")
