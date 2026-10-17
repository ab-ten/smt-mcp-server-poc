"""MCP用画像ファイルの検証と、元データの読み込みを担当します。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image as PillowImage
from PIL import UnidentifiedImageError


def parse_image_extensions(value: str) -> frozenset[str]:
  """カンマ区切りの拡張子を正規化します。空文字列は空集合を返します。

  拡張子がPillowで対応しているかはここでは検査せず、読み取り時に判断します。
  """
  extensions = set()
  for item in value.split(","):
    extension = item.strip().casefold()
    if extension:
      extensions.add(extension if extension.startswith(".") else f".{extension}")
  return frozenset(extensions)


def read_validated_image(path: Path, max_bytes: int, max_pixels: int) -> tuple[bytes, str]:
  """画像を検査し、変更していない元のバイト列とMIMEタイプを返します。

  拡張子に対応するPillowデコーダで読み込み、形式・寸法・画素データを
  検査します。未対応形式、形式不一致、破損画像、制限超過はValueErrorです。
  アニメーション画像では最初のフレームのみを検証します。
  """
  if max_bytes < 1 or max_pixels < 1:
    raise ValueError("image size limits must be positive")

  pillow_format = PillowImage.registered_extensions().get(path.suffix.casefold())
  if pillow_format is None:
    raise ValueError("image format is not supported by Pillow")

  with path.open("rb") as file:
    data = file.read(max_bytes+1)
  if len(data) > max_bytes:
    raise ValueError("image file exceeds MAX_IMAGE_BYTES")

  try:
    with PillowImage.open(BytesIO(data), formats=[pillow_format]) as image:
      if image.width*image.height > max_pixels:
        raise ValueError("image dimensions exceed MAX_IMAGE_PIXELS")
      image.load()
      mime_type = image.get_format_mimetype()
  except (UnidentifiedImageError, OSError, PillowImage.DecompressionBombError) as exc:
    raise ValueError("image data is invalid or unsupported") from exc

  if not mime_type or not mime_type.startswith("image/"):
    raise ValueError("image MIME type is not supported by MCP")

  return data, mime_type
