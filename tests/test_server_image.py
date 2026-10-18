from __future__ import annotations

import base64
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image as PillowImage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

auth_module = types.ModuleType("auth")
auth_module.auth_settings = None
auth_module.token_verifier = None
sys.modules["auth"] = auth_module

import server  # noqa: E402


class ReadImageToolTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)
    self.old_root = server.WORKSPACE_ROOT
    self.old_exts = server.MCP_IMAGE_EXTS
    server.WORKSPACE_ROOT = server.FileRoot(path=self.root)
    server.MCP_IMAGE_EXTS = server.parse_image_extensions(".png,.jpg,.bmp,.unknown")
    self.png_path = self.root / "picture.png"
    PillowImage.new("RGB", (8, 7), (14, 50, 116)).save(self.png_path)

  def tearDown(self):
    server.WORKSPACE_ROOT = self.old_root
    server.MCP_IMAGE_EXTS = self.old_exts
    self.tmp.cleanup()

  def _allow(self, extension: str):
    (self.root / ".mcpignore").write_text(f"allow **/*{extension}\n", encoding="utf-8")

  def test_denied_by_default(self):
    with self.assertRaisesRegex(ValueError, "not allowed"):
      server.read_image("picture.png")
    self.assertNotIn("picture.png", [item["path"] for item in server.list_files()])

  def test_explicit_policy_preserves_bytes(self):
    self._allow(".png")
    content = server.read_image("picture.png").to_image_content()
    self.assertEqual("image/png", getattr(content, "mimeType", getattr(content, "mime_type", None)))
    self.assertEqual(self.png_path.read_bytes(), base64.b64decode(content.data))
    self.assertIn("picture.png", [item["path"] for item in server.list_files()])

  def test_extension_not_configured(self):
    self._allow(".png")
    server.MCP_IMAGE_EXTS = server.parse_image_extensions("")
    with self.assertRaisesRegex(ValueError, "not configured"):
      server.read_image("picture.png")

  def test_configured_but_unsupported_extension(self):
    bad_path = self.root / "picture.unknown"
    bad_path.write_bytes(self.png_path.read_bytes())
    self._allow(".unknown")
    with self.assertRaisesRegex(ValueError, "not supported by Pillow"):
      server.read_image("picture.unknown")

  def test_unsupported_content_for_extension(self):
    bad_path = self.root / "picture.jpg"
    bad_path.write_bytes(self.png_path.read_bytes())
    self._allow(".jpg")
    with self.assertRaisesRegex(ValueError, "invalid or unsupported"):
      server.read_image("picture.jpg")

  def test_non_sdk_standard_format_has_correct_mime(self):
    path = self.root / "picture.bmp"
    PillowImage.new("RGB", (8, 7)).save(path)
    self._allow(".bmp")
    self.assertEqual("image/bmp", server.read_image("picture.bmp").to_image_content().mimeType)

  def test_parent_traversal_rejected(self):
    self._allow(".png")
    with self.assertRaisesRegex(ValueError, "parent-directory traversal"):
      server.read_image("../picture.png")

  def test_symlink_rejected(self):
    linked = self.root / "linked.png"
    try:
      linked.symlink_to(self.png_path)
    except (NotImplementedError, OSError):
      self.skipTest("symlink unavailable")
    self._allow(".png")
    with self.assertRaisesRegex(ValueError, "symlinks are not followed"):
      server.read_image("linked.png")

  def test_size_limit(self):
    self._allow(".png")
    with patch.object(server, "MAX_IMAGE_BYTES", 8):
      with self.assertRaisesRegex(ValueError, "MAX_IMAGE_BYTES"):
        server.read_image("picture.png")

  def test_pixel_limit(self):
    self._allow(".png")
    with patch.object(server, "MAX_IMAGE_PIXELS", 40):
      with self.assertRaisesRegex(ValueError, "MAX_IMAGE_PIXELS"):
        server.read_image("picture.png")

  def test_inbox_image_uses_its_own_policy(self):
    with tempfile.TemporaryDirectory() as tmp:
      inbox_path = Path(tmp)
      image_path = inbox_path / "sample.png"
      image_path.write_bytes(self.png_path.read_bytes())

      with patch.object(server, "INBOX_ROOT", server.FileRoot(path=inbox_path)):
        with self.assertRaisesRegex(ValueError, "not allowed"):
          server.read_inbox_image("sample.png")

        (inbox_path / ".mcpignore").write_text(
          "allow **/*.png\n", encoding="utf-8"
        )

        content = server.read_inbox_image("sample.png").to_image_content()
        self.assertEqual("image/png", content.mimeType)
        self.assertEqual(image_path.read_bytes(), base64.b64decode(content.data))

        with self.assertRaisesRegex(ValueError, "not allowed"):
          server.read_image("picture.png")

        with self.assertRaisesRegex(ValueError, "parent-directory traversal"):
          server.read_inbox_image("../sample.png")


if __name__ == "__main__":
  unittest.main()
