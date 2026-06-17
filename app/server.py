from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pathspec import PathSpec
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

from auth import auth_settings, token_verifier


EntryType = Literal["dir", "file"]
PolicyDecision = Literal["ignore", "allow", "fallback"]

MCP_HTTP_HOST = os.environ.get("MCP_HTTP_HOST", "127.0.0.1")
MCP_HTTP_PORT = int(os.environ.get("MCP_HTTP_PORT", "8000"))
MCP_HTTP_PATH = os.environ.get("MCP_HTTP_PATH", "/mcp")


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
LIST_FILES_MAX_ENTRIES = 1000
MCP_IGNORE_NAME = ".mcpignore"

DEFAULT_ALLOW_EXTS = {
  ".py", ".pyi", ".rs", ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
  ".cs", ".java", ".kt", ".kts", ".go", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
  ".el", ".lua", ".rb", ".php", ".swift", ".m", ".mm",
  ".md", ".txt", ".rst", ".adoc",
  ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml",
  ".sql", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
  ".uplugin", ".uproject", ".build.cs", ".target.cs",
}

ALLOW_NAMES = {
  "Dockerfile", "Makefile", "CMakeLists.txt", "LICENSE",
}

DEFAULT_IGNORE_DIRS = {
  ".git", ".hg", ".svn",
  "node_modules", ".venv", "venv", "__pycache__",
  ".mypy_cache", ".pytest_cache", ".ruff_cache",
  "target", "dist", "build", ".next", ".turbo",
}

HARD_DENY_PATTERNS = (
  "**/.env",
  "**/.env.*",
  "**/.npmrc",
  "**/.pypirc",
  "**/.netrc",
  "**/id_rsa",
  "**/id_ed25519",
  "**/id_dsa",
  "**/id_ecdsa",
  "**/known_hosts",
  "**/*.pem",
  "**/*.key",
  "**/*.p12",
  "**/*.pfx",
  "**/*.kdbx",
  "**/*.age",
  "**/*.sqlite",
  "**/*.db",
  "**/*.mdb",
  f"**/{MCP_IGNORE_NAME}",
)

HARD_DENY_SPEC = PathSpec.from_lines(
  "gitwildmatch",
  [pattern.casefold() for pattern in HARD_DENY_PATTERNS],
)
DEFAULT_IGNORE_RULES = [
  f"ignore {name}/"
  for name in sorted(DEFAULT_IGNORE_DIRS)
]
DEFAULT_ALLOW_RULES = [
  f"allow **/*{ext}"
  for ext in sorted(DEFAULT_ALLOW_EXTS, key=lambda value: (len(value), value))
] + [
  f"allow {name}"
  for name in sorted(ALLOW_NAMES)
]

FALLBACK_ENCODING_EXTS = {".bat", ".cmd"}

@dataclass(frozen=True)
class McpIgnorePolicy:
  """MCP 公開ポリシーの ignore / allow パターンを表します。"""
  ignore_patterns: tuple[str, ...]
  allow_patterns: tuple[str, ...]

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

def _expand_mcpignore_pattern(pattern: str) -> tuple[str, ...]:
  """ディレクトリパターンを配下のファイルにも明示的に適用します。"""
  if not pattern.endswith("/"):
    return (pattern,)

  prefix = "!" if pattern.startswith("!") else ""
  path_pattern = pattern[1:] if pattern.startswith("!") else pattern
  return (pattern, f"{prefix}{path_pattern}**")

def _parse_mcpignore_lines(lines: list[str]) -> McpIgnorePolicy:
  """`.mcpignore` の行を MCP 公開ポリシールールへ変換します。"""
  ignore_patterns: list[str] = []
  allow_patterns: list[str] = []
  for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
      continue

    command, _, rest = stripped.partition(" ")
    if command == "ignore" and rest.strip():
      decision: Literal["ignore", "allow"] = "ignore"
      pattern = rest.strip()
    elif command == "allow" and rest.strip():
      decision = "allow"
      pattern = rest.strip()
    else:
      decision = "ignore"
      pattern = stripped

    expanded_patterns = _expand_mcpignore_pattern(pattern)
    if decision == "ignore":
      ignore_patterns.extend(expanded_patterns)
    else:
      allow_patterns.extend(expanded_patterns)
  return McpIgnorePolicy(
    ignore_patterns=tuple(ignore_patterns),
    allow_patterns=tuple(allow_patterns),
  )

def _read_mcpignore_policy(ignore_dir: Path) -> McpIgnorePolicy:
  """指定ディレクトリの .mcpignore からポリシールールを読み込みます。"""
  ignore_file = ignore_dir / MCP_IGNORE_NAME
  if not ignore_file.is_file() or ignore_file.is_symlink():
    return McpIgnorePolicy(ignore_patterns=(), allow_patterns=())
  return _parse_mcpignore_lines(ignore_file.read_text(encoding="utf-8").splitlines())

def _merge_mcpignore_policies(policies: list[McpIgnorePolicy]) -> McpIgnorePolicy:
  """複数の MCP 公開ポリシーを一つの policy として結合します。"""
  ignore_patterns: list[str] = []
  allow_patterns: list[str] = []
  for policy in policies:
    ignore_patterns.extend(policy.ignore_patterns)
    allow_patterns.extend(policy.allow_patterns)
  return McpIgnorePolicy(
    ignore_patterns=tuple(ignore_patterns),
    allow_patterns=tuple(allow_patterns),
  )

def _policy_for_dir(policy_dir: Path) -> McpIgnorePolicy:
  """指定ディレクトリに存在する MCP 公開ポリシールールを返します。"""
  policies: list[McpIgnorePolicy] = []
  if policy_dir == ROOT:
    policies.append(_parse_mcpignore_lines(DEFAULT_IGNORE_RULES + DEFAULT_ALLOW_RULES))
  policies.append(_read_mcpignore_policy(policy_dir))
  return _merge_mcpignore_policies(policies)

def _pathspec_candidates(path: Path, policy_dir: Path, is_dir: bool) -> list[str]:
  """pathspec に渡す相対パス候補を返します。"""
  rel = path.relative_to(policy_dir).as_posix()
  candidates = [rel]
  if is_dir:
    candidates.append(f"{rel}/")
  return candidates

def _mcpignore_decision(policy: McpIgnorePolicy, candidates: list[str]) -> PolicyDecision:
  """ルール列に対する公開ポリシー判定を返します。"""
  ignore_spec = PathSpec.from_lines("gitwildmatch", policy.ignore_patterns)
  if any(ignore_spec.match_file(candidate) for candidate in candidates):
    return "ignore"

  allow_spec = PathSpec.from_lines("gitwildmatch", policy.allow_patterns)
  if any(allow_spec.match_file(candidate) for candidate in candidates):
    return "allow"

  return "fallback"

def _file_policy_decision(path: Path) -> PolicyDecision:
  """下位から上位へ fallback しながらファイル公開ポリシーを判定します。"""
  for policy_dir in reversed(_mcpignore_dirs_for(path)):
    decision = _mcpignore_decision(
      _policy_for_dir(policy_dir),
      _pathspec_candidates(path, policy_dir, is_dir=False),
    )
    if decision != "fallback":
      return decision
  return "ignore"

def _is_hard_denied_path(path: Path, is_dir: bool = False) -> bool:
  """hard deny の pathspec に一致するかを大小文字を区別せずに判定します。"""
  candidates = [
    candidate.casefold()
    for candidate in _pathspec_candidates(path, ROOT, is_dir)
  ]
  return any(HARD_DENY_SPEC.match_file(candidate) for candidate in candidates)

def _is_directory_ignored_by_policy(path: Path) -> bool:
  """ディレクトリが .mcpignore の ignore ルールに一致するか判定します。"""
  if path == ROOT:
    return False

  for policy_dir in _mcpignore_dirs_for(path):
    policy = _policy_for_dir(policy_dir)
    ignore_spec = PathSpec.from_lines("gitwildmatch", policy.ignore_patterns)
    candidates = _pathspec_candidates(path, policy_dir, True)
    if any(ignore_spec.match_file(candidate) for candidate in candidates):
      return True
  return False

def _has_ignored_ancestor_dir(path: Path) -> bool:
  """親ディレクトリのいずれかが ignore されているか判定します。"""
  for directory in _ancestor_dirs_from_root(path.parent)[1:]:
    if _is_directory_ignored_by_policy(directory):
      return True
  return False

def _is_allowed_file(path: Path) -> bool:
  """MCP ツールで公開可能なファイルか判定します。"""
  if not path.is_file() or path.is_symlink():
    return False
  if _is_hard_denied_path(path):
    return False
  if _has_ignored_ancestor_dir(path):
    return False
  return _file_policy_decision(path) == "allow"

def _is_skipped_dir(path: Path) -> bool:
  """走査対象から除外するディレクトリかどうかを判定します。"""
  return (
    path.is_symlink()
    or _is_hard_denied_path(path, is_dir=True)
    or _is_directory_ignored_by_policy(path)
  )

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
  if not _is_allowed_file(path):
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

def _entry_type(path: Path) -> EntryType | None:
  """走査可能なエントリ種別を返します。判定できない場合は None を返します。"""
  try:
    if path.is_symlink():
      return None
    if path.is_dir():
      return "dir"
    if path.is_file():
      return "file"
  except OSError:
    return None
  return None

def _walk_children(base: Path):
  """指定ディレクトリ直下の走査可能なエントリを安全に列挙します。"""
  try:
    children = [
      (child, entry_type)
      for child in base.iterdir()
      if (entry_type := _entry_type(child)) is not None
    ]
  except OSError:
    return

  yield from sorted(children, key=lambda item: (item[1] != "dir", item[0].name.lower()))

def _can_list_dir(path: Path) -> bool:
  """指定ディレクトリを列挙できるか確認します。"""
  try:
    next(path.iterdir(), None)
  except OSError:
    return False
  return True

def _walk_entries(base: Path):
  """指定パス配下の走査可能なファイルとディレクトリを再帰的に列挙します。"""
  if base.is_file():
    yield base, "file"
    return
  if base != ROOT and _is_skipped_dir(base):
    return

  for child, entry_type in _walk_children(base):
    if entry_type == "dir":
      if _is_skipped_dir(child):
        continue
      if not _can_list_dir(child):
        continue
      yield child, "dir"
      yield from _walk_entries(child)
    elif entry_type == "file":
      yield child, "file"

def _walk_files(base: Path):
  """指定パス配下の走査可能なファイルを再帰的に列挙します。"""
  for path, entry_type in _walk_entries(base):
    if entry_type == "file":
      yield path

def _list_public_paths() -> list[str]:
  """MCP ツールで公開されるパスを一覧化します。"""
  if not ROOT.exists():
    raise ValueError("MCP_ROOT does not exist")
  if not ROOT.is_dir():
    raise ValueError("MCP_ROOT is not a directory")

  entries = list_files(recursive=True, max_entries=sys.maxsize)
  return [
    f"{entry['path']}/" if entry["type"] == "dir" else str(entry["path"])
    for entry in entries
  ]


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

  max_entries = max(1, min(max_entries, LIST_FILES_MAX_ENTRIES))
  entries: list[dict[str, Any]] = []

  if recursive:
    for child, entry_type in _walk_entries(base):
      if len(entries) >= max_entries:
        break

      if entry_type == "file" and not _is_allowed_file(child):
        continue

      entry: dict[str, Any] = {
        "path": _rel(child),
        "type": entry_type,
      }

      if entry_type == "file":
        entry["size"] = child.stat().st_size

      entries.append(entry)
  else:
    for child, entry_type in sorted(_walk_children(base), key=lambda item: item[0].name.lower()):
      if len(entries) >= max_entries:
        break
      if entry_type == "dir":
        if _is_skipped_dir(child):
          continue
        entries.append({
          "path": _rel(child),
          "type": "dir",
        })
      elif entry_type == "file" and _is_allowed_file(child):
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
    if not _is_allowed_file(file_path):
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


def _parse_args(argv: list[str]) -> argparse.Namespace:
  """コマンドライン引数を解析します。"""
  parser = argparse.ArgumentParser(description="Run the local files MCP server.")
  parser.add_argument(
    "--list",
    action="store_true",
    help="list paths exposed by the MCP policy and exit",
  )
  return parser.parse_args(argv)

def _main(argv: list[str]) -> int:
  """CLI 実行時の処理を行います。"""
  global LIST_FILES_MAX_ENTRIES

  args = _parse_args(argv)
  if args.list:
    previous_list_files_max_entries = LIST_FILES_MAX_ENTRIES
    try:
      LIST_FILES_MAX_ENTRIES = sys.maxsize
      for path in _list_public_paths():
        print(path)
    except Exception as exc:
      print(f"error: {exc}", file=sys.stderr)
      return 1
    finally:
      LIST_FILES_MAX_ENTRIES = previous_list_files_max_entries
    return 0

  mcp.run(transport="streamable-http")
  return 0


if __name__ == "__main__":
  raise SystemExit(_main(sys.argv[1:]))
