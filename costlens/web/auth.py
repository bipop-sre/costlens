"""Authentication utilities for web API."""

from __future__ import annotations

from fastapi import HTTPException, Header


async def verify_token(authorization: str = Header(None)):
    """Verify API token for protected endpoints."""
    from costlens.config import get_settings
    settings = get_settings()
    
    # If no token configured, allow all access
    if not settings.web_auth_token:
        return
    
    # Check Authorization header
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    token = authorization.replace("Bearer ", "")
    if token != settings.web_auth_token:
        raise HTTPException(status_code=401, detail="Invalid token")
