from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

auth_module = types.ModuleType("auth")
auth_module.auth_settings = None
auth_module.token_verifier = None
sys.modules["auth"] = auth_module

pathspec_module = types.ModuleType("pathspec")

class PathSpec:
  patterns: list[object] = []

  @classmethod
  def from_lines(cls, _pattern_factory: str, _lines: list[str]):
    return cls()

  def match_file(self, _path: str) -> bool:
    return False

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


if __name__ == "__main__":
  unittest.main()
