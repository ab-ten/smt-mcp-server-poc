from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image as PillowImage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from image_reader import parse_image_extensions, read_validated_image


class ImageReaderTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)

  def tearDown(self):
    self.tmp.cleanup()

  def _create_image(self, image_format: str, extension: str, size=(8, 7)) -> Path:
    path = self.root / f"test{extension}"
    PillowImage.new("RGB", size, (14, 50, 116)).save(path, format=image_format)
    return path

  def test_parse_extensions(self):
    self.assertEqual(frozenset({".png", ".jpg", ".xyz"}), parse_image_extensions("PNG, .JPG , xyz,"))
    self.assertEqual(frozenset(), parse_image_extensions(""))

  def test_supported_formats_keep_original_bytes_and_mime(self):
    for image_format, extension, expected_mime in [
      ("PNG", ".png", "image/png"),
      ("JPEG", ".jpg", "image/jpeg"),
      ("WEBP", ".webp", "image/webp"),
      ("GIF", ".gif", "image/gif"),
      ("BMP", ".bmp", "image/bmp"),
      ("TIFF", ".tiff", "image/tiff"),
    ]:
      with self.subTest(image_format=image_format):
        if not PillowImage.registered_extensions().get(extension):
          self.skipTest(f"Pillow does not support {image_format}")
        path = self._create_image(image_format, extension)
        data, mime = read_validated_image(path, 4194304, 16000000)
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(expected_mime, mime)

  def test_unknown_extension_fails_even_if_content_is_png(self):
    path = self._create_image("PNG", ".png")
    bad_path = path.with_suffix(".unknown")
    bad_path.write_bytes(path.read_bytes())
    with self.assertRaisesRegex(ValueError, "not supported by Pillow"):
      read_validated_image(bad_path, 4194304, 16000000)

  def test_extension_content_mismatch_is_rejected(self):
    path = self._create_image("PNG", ".png")
    bad_path = path.with_suffix(".jpg")
    bad_path.write_bytes(path.read_bytes())
    with self.assertRaisesRegex(ValueError, "invalid or unsupported"):
      read_validated_image(bad_path, 4194304, 16000000)

  def test_corrupted_image_fails(self):
    path = self.root / "corrupt.png"
    path.write_bytes(b"not really an image")
    with self.assertRaisesRegex(ValueError, "invalid or unsupported"):
      read_validated_image(path, 4194304, 16000000)

  def test_size_limit_fails(self):
    path = self._create_image("PNG", ".png")
    with self.assertRaisesRegex(ValueError, "MAX_IMAGE_BYTES"):
      read_validated_image(path, max_bytes=8, max_pixels=16000000)

  def test_pixel_limit_fails(self):
    path = self._create_image("PNG", ".png")
    with self.assertRaisesRegex(ValueError, "MAX_IMAGE_PIXELS"):
      read_validated_image(path, max_bytes=4194304, max_pixels=40)

  def test_invalid_limits_fail(self):
    path = self._create_image("PNG", ".png")
    with self.assertRaises(ValueError):
      read_validated_image(path, max_bytes=0, max_pixels=16000000)


if __name__ == "__main__":
  unittest.main()
