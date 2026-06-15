from __future__ import annotations

import asyncio
import os
from typing import Any

import jwt
from jwt import InvalidTokenError, PyJWKClient
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl


def _env_bool(name: str, default: bool = False) -> bool:
  """環境変数の値を真偽値として解釈します。"""
  value = os.environ.get(name)
  if value is None:
    return default
  return value.lower() in ("1", "true", "yes", "on")

def _split_space_or_comma_list(value: str) -> list[str]:
  """空白またはカンマ区切りの文字列をリストに変換します。"""
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
MCP_HTTP_PORT = int(os.environ.get("MCP_HTTP_PORT", "8000"))

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
  """Cognito アクセストークンを検証する TokenVerifier です。"""

  def __init__(self):
    """JWKS クライアントを初期化します。"""
    self._jwks_client = PyJWKClient(COGNITO_JWKS_URL)

  async def verify_token(self, token: str) -> AccessToken | None:
    """JWT を検証し、MCP 認可に使用するアクセストークン情報を返します。"""
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
    """JWKS の署名鍵を使用して JWT をデコードします。"""
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
  """Cognito 認証が有効な場合に MCP 認証設定を作成します。"""
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
