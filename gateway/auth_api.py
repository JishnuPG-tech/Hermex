import os
import time
import uuid
import datetime
import logging
from typing import Optional, Dict, Any, Union
from fastapi import APIRouter, Request, HTTPException, Header, Response
from pydantic import BaseModel, Field
import jwt
import httpx

logger = logging.getLogger("auth_api")
router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "292824298430-113kq16cbpq6i02jin424gb1mk5ebm40.apps.googleusercontent.com")
JWT_SECRET = os.getenv("HERMES_JWT_SECRET", "TfbVB8E4Dsq2BUU9INKauUJ_qENXka1mR6eNoID6Z0wtB1GO_kM62HP-0FqE-oE-")
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"

ADMIN_EMAILS = {"jishnupg2005@gmail.com", "jishnu.pg@gmail.com"}

_GOOGLE_JWKS_CACHE: Dict[str, Any] = {}
_GOOGLE_JWKS_EXPIRY: float = 0.0

class GoogleAuthRequest(BaseModel):
    id_token: Optional[str] = None
    token: Optional[str] = None
    join_token: Optional[str] = None
    login_token: Optional[str] = None
    recaptcha_token: Optional[str] = ""
    recaptcha_site_key: Optional[str] = ""
    play_integrity_token: Optional[str] = None
    source: Optional[str] = "google_mobile"

async def _get_google_jwks() -> Dict[str, Any]:
    global _GOOGLE_JWKS_CACHE, _GOOGLE_JWKS_EXPIRY
    now = time.time()
    if _GOOGLE_JWKS_CACHE and now < _GOOGLE_JWKS_EXPIRY:
        return _GOOGLE_JWKS_CACHE
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(GOOGLE_CERTS_URL)
        if resp.status_code == 200:
            _GOOGLE_JWKS_CACHE = resp.json()
            _GOOGLE_JWKS_EXPIRY = now + 3600
            return _GOOGLE_JWKS_CACHE
        raise HTTPException(status_code=500, detail="Failed to fetch Google public keys")

async def verify_google_id_token(token_str: str) -> Dict[str, Any]:
    try:
        jwks = await _get_google_jwks()
        unverified_header = jwt.get_unverified_header(token_str)
        kid = unverified_header.get("kid")
        
        key = None
        for k in jwks.get("keys", []):
            if k.get("kid") == kid:
                key = jwt.algorithms.RSAAlgorithm.from_jwk(k)
                break
                
        if key:
            payload = jwt.decode(
                token_str,
                key=key,
                algorithms=["RS256"],
                audience=GOOGLE_CLIENT_ID,
                issuer=["accounts.google.com", "https://accounts.google.com"]
            )
            return payload
    except Exception as err:
        logger.warning(f"Direct JWK verification failed, trying tokeninfo fallback: {err}")

    # Fallback to direct tokeninfo verification
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={token_str}")
        if resp.status_code == 200:
            payload = resp.json()
            aud = payload.get("aud")
            if aud != GOOGLE_CLIENT_ID:
                raise HTTPException(status_code=401, detail=f"Token audience mismatch: {aud}")
            return payload
    raise HTTPException(status_code=401, detail="Invalid Google token key")

def create_session_token(user_data: Dict[str, Any]) -> str:
    now = datetime.datetime.utcnow()
    payload = {
        "sub": user_data.get("id"),
        "email": user_data.get("email"),
        "name": user_data.get("name"),
        "picture": user_data.get("picture"),
        "is_admin": user_data.get("is_admin", False),
        "tier": user_data.get("tier", "claude_max"),
        "iat": now,
        "exp": now + datetime.timedelta(days=90)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def decode_session_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception as e:
        logger.debug(f"JWT decode error: {e}")
        return None

# Endpoints matching Retrofit @POST("auth/verify_google_mobile") & fallback routes
@router.post("/api/auth/verify_google_mobile")
@router.post("/auth/verify_google_mobile")
@router.post("/api/v1/auth/verify_google_mobile")
@router.post("/hermes/api/auth/verify_google_mobile")
@router.post("/hermes/auth/verify_google_mobile")
@router.post("/api/v1/auth/google")
@router.post("/api/auth/google")
@router.post("/hermes/api/v1/auth/google")
@router.post("/hermes/api/auth/google")
async def google_login(payload: GoogleAuthRequest, response: Response):
    token_str = payload.token or payload.id_token
    if not token_str:
        raise HTTPException(status_code=400, detail="Missing Google ID token in request")

    try:
        id_info = await verify_google_id_token(token_str)
        
        user_id = id_info.get("sub", str(uuid.uuid4()))
        email = id_info.get("email", "").lower().strip()
        name = id_info.get("name", email.split("@")[0] if email else "Hermes Admin")
        now_iso = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        is_super_admin = email in ADMIN_EMAILS or email == "jishnupg2005@gmail.com"
        
        user_obj = {
            "id": f"usr_{user_id[:16]}",
            "google_sub": user_id,
            "email": email,
            "name": f"{name} (Admin Max)" if is_super_admin else name,
            "picture": id_info.get("picture", ""),
            "is_admin": is_super_admin,
            "tier": "claude_max"
        }

        # Issue Hermes session token (JWT)
        session_key = create_session_token(user_obj)
        
        # Set session cookie for web/cronet clients
        response.set_cookie(
            key="sessionKey",
            value=session_key,
            max_age=60*60*24*90,
            httponly=True,
            samesite="lax",
            secure=True
        )

        org_id = f"org_{user_id[:16]}"
        from gateway.claude_rest_api import MODELS_CATALOG
        
        account_data = {
            "uuid": user_obj["id"],
            "email_address": email,
            "full_name": user_obj["name"],
            "display_name": user_obj["name"],
            "created_at": now_iso,
            "updated_at": now_iso,
            "is_verified": True,
            "settings": None,
            "memberships": [
                {
                    "organization": {
                        "id": org_id,
                        "uuid": org_id,
                        "name": f"{name}'s Admin Org" if is_super_admin else f"{name}'s Organization",
                        "settings": {"billing_tier": "default"},
                        "capabilities": [
                            "chat",
                            "claude_pro",
                            "claude_max",
                            "raven",
                            "artifacts",
                            "projects",
                            "custom_connectors",
                            "voice",
                            "mcp"
                        ],
                        "claude_ai_bootstrap_models_config": MODELS_CATALOG,
                        "raven_type": None,
                        "rate_limit_tier": "claude_max",
                        "billing_type": "stripe",
                        "rate_limit_upsell": None,
                        "subscription_pause": "ABSENT"
                    },
                    "role": "admin",
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "notification_preferences": None
                }
            ]
        }

        # Contract matching Lcom/anthropic/hermes/api/login/VerifyResponse
        return {
            "success": True,
            "account": account_data,
            "secret": session_key,
            "sessionKey": session_key,
            "sso_url": None,
            "state": "COMPLETE",
            "created": False
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google OAuth verification failed: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail=f"Google authentication failed: {str(e)}")

@router.get("/api/v1/auth/me")
@router.get("/api/auth/me")
@router.get("/hermes/api/v1/auth/me")
async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    payload = decode_session_token(authorization)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid session token")
        
    return {
        "authenticated": True,
        "user": payload
    }
