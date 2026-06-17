from __future__ import annotations

import fnmatch
import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

auth_module = types.ModuleType("auth")
auth_module.auth_settings = None
auth_module.token_verifier = None
sys.modules["auth"] = auth_module

pathspec_module = types.ModuleType("pathspec")

class PathSpec:
  def __init__(self, patterns: list[str] | None = None):
    self.patterns = patterns or []

  @classmethod
  def from_lines(cls, _pattern_factory: str, lines: list[str]):
    return cls([line.strip() for line in lines if line.strip()])

  def match_file(self, path: str) -> bool:
    normalized = path.replace("\\", "/")
    path_without_slash = normalized.rstrip("/")
    basename = Path(path_without_slash).name

    matched = False
    for pattern in self.patterns:
      include = not pattern.startswith("!")
      normalized_pattern = pattern[1:] if pattern.startswith("!") else pattern
      if self._match_pattern(normalized_pattern, normalized, path_without_slash, basename):
        matched = include
    return matched

  def _match_pattern(
    self,
    pattern: str,
    path: str,
    path_without_slash: str,
    basename: str,
  ) -> bool:
    if pattern.endswith("/"):
      prefix = pattern.rstrip("/")
      return path_without_slash == prefix or path_without_slash.startswith(f"{prefix}/")

    if pattern.startswith("**/"):
      rest = pattern[3:]
      return (
        fnmatch.fnmatchcase(path_without_slash, pattern)
        or fnmatch.fnmatchcase(path_without_slash, rest)
        or fnmatch.fnmatchcase(basename, rest)
      )

    if "/" not in pattern:
      return fnmatch.fnmatchcase(basename, pattern)

    return fnmatch.fnmatchcase(path_without_slash, pattern)

pathspec_module.PathSpec = PathSpec
sys.modules["pathspec"] = pathspec_module

mcp_module = types.ModuleType("mcp")
mcp_server_module = types.ModuleType("mcp.server")
mcp_fastmcp_module = types.ModuleType("mcp.server.fastmcp")

class FastMCP:
  def __init__(self, *_args, **_kwargs):
    pass

  def tool(self):
    def decorator(func):
      return func
    return decorator

  def custom_route(self, *_args, **_kwargs):
    def decorator(func):
      return func
    return decorator

  def run(self, *_args, **_kwargs):
    pass

mcp_fastmcp_module.FastMCP = FastMCP
sys.modules["mcp"] = mcp_module
sys.modules["mcp.server"] = mcp_server_module
sys.modules["mcp.server.fastmcp"] = mcp_fastmcp_module

starlette_module = types.ModuleType("starlette")
starlette_responses_module = types.ModuleType("starlette.responses")

class JSONResponse:
  def __init__(self, content):
    self.content = content

starlette_responses_module.JSONResponse = JSONResponse
sys.modules["starlette"] = starlette_module
sys.modules["starlette.responses"] = starlette_responses_module

import server  # noqa: E402


class WalkEntriesPermissionTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)
    self.old_root = server.ROOT
    server.ROOT = self.root

    (self.root / "readable").mkdir()
    (self.root / "readable" / "match.txt").write_text("needle\n", encoding="utf-8")
    (self.root / "root.txt").write_text("needle\n", encoding="utf-8")
    (self.root / "denied").mkdir()
    (self.root / "denied" / "hidden.txt").write_text("needle\n", encoding="utf-8")

  def tearDown(self):
    server.ROOT = self.old_root
    self.tmp.cleanup()

  def _deny_iterdir(self, denied: Path):
    original_iterdir = Path.iterdir

    def guarded_iterdir(path: Path):
      if path == denied:
        raise PermissionError("permission denied")
      return original_iterdir(path)

    return patch.object(Path, "iterdir", guarded_iterdir)

  def test_recursive_list_skips_unreadable_directory(self):
    with self._deny_iterdir(self.root / "denied"):
      entries = server.list_files(recursive=True)

    paths = {entry["path"] for entry in entries}
    self.assertIn("readable", paths)
    self.assertIn("readable/match.txt", paths)
    self.assertIn("root.txt", paths)
    self.assertNotIn("denied", paths)
    self.assertNotIn("denied/hidden.txt", paths)

  def test_find_files_continues_after_unreadable_directory(self):
    with self._deny_iterdir(self.root / "denied"):
      matches = server.find_files("*.txt")

    self.assertIn("readable/match.txt", matches)
    self.assertIn("root.txt", matches)
    self.assertNotIn("denied/hidden.txt", matches)

  def test_search_text_continues_after_unreadable_directory(self):
    with self._deny_iterdir(self.root / "denied"):
      results = server.search_text("needle")

    paths = {result["path"] for result in results}
    self.assertIn("readable/match.txt", paths)
    self.assertIn("root.txt", paths)
    self.assertNotIn("denied/hidden.txt", paths)


class McpIgnorePolicyTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)
    self.old_root = server.ROOT
    server.ROOT = self.root

  def tearDown(self):
    server.ROOT = self.old_root
    self.tmp.cleanup()

  def _paths(self, recursive: bool = True) -> set[str]:
    return {entry["path"] for entry in server.list_files(recursive=recursive)}

  def test_default_allow_exposes_readme_and_python(self):
    (self.root / "README.md").write_text("docs\n", encoding="utf-8")
    (self.root / "app").mkdir()
    (self.root / "app" / "server.py").write_text("print('ok')\n", encoding="utf-8")

    paths = self._paths()

    self.assertIn("README.md", paths)
    self.assertIn("app/server.py", paths)

  def test_root_ignore_overrides_default_allow(self):
    (self.root / ".mcpignore").write_text("ignore **/*.md\n", encoding="utf-8")
    (self.root / "README.md").write_text("docs\n", encoding="utf-8")

    self.assertNotIn("README.md", self._paths())
    with self.assertRaises(ValueError):
      server.read_file("README.md")

  def test_lower_allow_overrides_upper_ignore(self):
    (self.root / ".mcpignore").write_text("ignore **/*.el\n", encoding="utf-8")
    (self.root / "pkg").mkdir()
    (self.root / "pkg" / ".mcpignore").write_text("allow **/*.el\n", encoding="utf-8")
    (self.root / "pkg" / "init.el").write_text("(message \"ok\")\n", encoding="utf-8")

    self.assertIn("pkg/init.el", self._paths())

  def test_lower_fallback_uses_upper_policy(self):
    (self.root / ".mcpignore").write_text("allow **/*.secret\n", encoding="utf-8")
    (self.root / "pkg").mkdir()
    (self.root / "pkg" / ".mcpignore").write_text("ignore **/*.other\n", encoding="utf-8")
    (self.root / "pkg" / "visible.secret").write_text("needle\n", encoding="utf-8")

    self.assertIn("pkg/visible.secret", self._paths())

  def test_lower_ignore_overrides_upper_allow(self):
    (self.root / ".mcpignore").write_text("allow **/*.secret\n", encoding="utf-8")
    (self.root / "pkg").mkdir()
    (self.root / "pkg" / ".mcpignore").write_text("ignore **/*.secret\n", encoding="utf-8")
    (self.root / "pkg" / "hidden.secret").write_text("needle\n", encoding="utf-8")

    self.assertNotIn("pkg/hidden.secret", self._paths())

  def test_ignore_wins_over_allow_in_same_mcpignore(self):
    (self.root / ".mcpignore").write_text(
      "\n".join([
        "allow **/*.secret",
        "ignore **/hidden.secret",
        "ignore **/also-hidden.secret",
        "allow **/also-hidden.secret",
      ]),
      encoding="utf-8",
    )
    (self.root / "visible.secret").write_text("needle\n", encoding="utf-8")
    (self.root / "hidden.secret").write_text("needle\n", encoding="utf-8")
    (self.root / "also-hidden.secret").write_text("needle\n", encoding="utf-8")

    paths = self._paths()

    self.assertIn("visible.secret", paths)
    self.assertNotIn("hidden.secret", paths)
    self.assertNotIn("also-hidden.secret", paths)

  def test_default_ignore_hides_generated_directories(self):
    (self.root / "node_modules" / "pkg").mkdir(parents=True)
    (self.root / "node_modules" / "pkg" / "index.ts").write_text("needle\n", encoding="utf-8")
    (self.root / "dist").mkdir()
    (self.root / "dist" / "out.py").write_text("print('hidden')\n", encoding="utf-8")

    paths = self._paths()

    self.assertNotIn("node_modules", paths)
    self.assertNotIn("node_modules/pkg/index.ts", paths)
    self.assertNotIn("dist", paths)
    self.assertNotIn("dist/out.py", paths)
    self.assertEqual([], server.find_files("index.ts"))
    self.assertEqual([], server.search_text("needle"))
    with self.assertRaises(ValueError):
      server.read_file("node_modules/pkg/index.ts")

  def test_root_mcpignore_can_unignore_default_ignore_and_allow_files(self):
    (self.root / ".mcpignore").write_text(
      "\n".join([
        "ignore !node_modules/",
        "allow node_modules/**/*.ts",
        "allow node_modules/**/.env",
      ]),
      encoding="utf-8",
    )
    (self.root / "node_modules" / "pkg").mkdir(parents=True)
    (self.root / "node_modules" / "pkg" / "index.ts").write_text("needle\n", encoding="utf-8")
    (self.root / "node_modules" / "pkg" / ".env").write_text("SECRET=1\n", encoding="utf-8")

    paths = self._paths()

    self.assertIn("node_modules", paths)
    self.assertIn("node_modules/pkg/index.ts", paths)
    self.assertNotIn("node_modules/pkg/.env", paths)
    self.assertEqual(["node_modules/pkg/index.ts"], server.find_files("index.ts"))
    self.assertEqual("needle", server.read_file("node_modules/pkg/index.ts")["text"])
    self.assertEqual("node_modules/pkg/index.ts", server.search_text("needle")[0]["path"])
    with self.assertRaises(ValueError):
      server.read_file("node_modules/pkg/.env")

  def test_parent_directory_ignore_cannot_be_revived_by_child_allow(self):
    (self.root / ".mcpignore").write_text("ignore hidden/\n", encoding="utf-8")
    (self.root / "hidden").mkdir()
    (self.root / "hidden" / ".mcpignore").write_text("allow **/*.py\n", encoding="utf-8")
    (self.root / "hidden" / "keep.py").write_text("print('no')\n", encoding="utf-8")

    paths = self._paths()

    self.assertNotIn("hidden", paths)
    self.assertNotIn("hidden/keep.py", paths)
    with self.assertRaises(ValueError):
      server.read_file("hidden/keep.py")

  def test_hard_deny_cannot_be_allowed(self):
    (self.root / ".mcpignore").write_text(
      "\n".join([
        "allow **/.env",
        "allow **/id_rsa",
        "allow **/*.sqlite",
        "allow **/*.SQLITE",
        "allow **/.mcpignore",
      ]),
      encoding="utf-8",
    )
    (self.root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (self.root / ".ENV").write_text("SECRET=1\n", encoding="utf-8")
    (self.root / "id_rsa").write_text("secret\n", encoding="utf-8")
    (self.root / "data.sqlite").write_text("secret\n", encoding="utf-8")
    (self.root / "DATA.SQLITE").write_text("secret\n", encoding="utf-8")

    paths = self._paths()

    self.assertNotIn(".env", paths)
    self.assertNotIn(".ENV", paths)
    self.assertNotIn("id_rsa", paths)
    self.assertNotIn("data.sqlite", paths)
    self.assertNotIn("DATA.SQLITE", paths)
    self.assertNotIn(".mcpignore", paths)
    for path in [".env", ".ENV", "id_rsa", "data.sqlite", "DATA.SQLITE", ".mcpignore"]:
      with self.assertRaises(ValueError):
        server.read_file(path)

  def test_recursive_list_includes_directories_but_not_ignored_subtree(self):
    (self.root / ".mcpignore").write_text("ignore ignored/\n", encoding="utf-8")
    (self.root / "visible").mkdir()
    (self.root / "visible" / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    (self.root / "ignored").mkdir()
    (self.root / "ignored" / "hidden.py").write_text("print('no')\n", encoding="utf-8")

    paths = self._paths()

    self.assertIn("visible", paths)
    self.assertIn("visible/ok.py", paths)
    self.assertNotIn("ignored", paths)
    self.assertNotIn("ignored/hidden.py", paths)

  def test_unknown_extension_is_ignored_without_policy(self):
    (self.root / "unknown.blob").write_text("needle\n", encoding="utf-8")

    self.assertNotIn("unknown.blob", self._paths())
    self.assertEqual([], server.find_files("*.blob"))
    self.assertEqual([], server.search_text("needle"))
    with self.assertRaises(ValueError):
      server.read_file("unknown.blob")


class CommandLineListTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)
    self.old_root = server.ROOT
    server.ROOT = self.root

  def tearDown(self):
    server.ROOT = self.old_root
    self.tmp.cleanup()

  def _run_main(self, *args: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
      code = server._main(list(args))
    return code, stdout.getvalue(), stderr.getvalue()

  def test_list_outputs_only_public_paths(self):
    (self.root / "README.md").write_text("docs\n", encoding="utf-8")
    (self.root / "app").mkdir()
    (self.root / "app" / "server.py").write_text("print('ok')\n", encoding="utf-8")
    (self.root / ".mcpignore").write_text("ignore **/*.md\n", encoding="utf-8")
    (self.root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (self.root / "unknown.blob").write_text("needle\n", encoding="utf-8")

    code, stdout, stderr = self._run_main("--list")

    self.assertEqual(0, code)
    self.assertEqual("", stderr)
    self.assertEqual(["app/", "app/server.py"], stdout.splitlines())

  def test_list_uses_list_files_without_entry_limit(self):
    for index in range(server.LIST_FILES_MAX_ENTRIES + 1):
      (self.root / f"file-{index:04}.txt").write_text("ok\n", encoding="utf-8")

    code, stdout, stderr = self._run_main("--list")

    self.assertEqual(0, code)
    self.assertEqual("", stderr)
    self.assertEqual(server.LIST_FILES_MAX_ENTRIES + 1, len(stdout.splitlines()))

  def test_list_returns_error_when_root_is_missing(self):
    server.ROOT = self.root / "missing"

    code, stdout, stderr = self._run_main("--list")

    self.assertEqual(1, code)
    self.assertEqual("", stdout)
    self.assertIn("MCP_ROOT does not exist", stderr)


if __name__ == "__main__":
  unittest.main()
