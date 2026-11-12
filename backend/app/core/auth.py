from __future__ import annotations

import os
import time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Header, HTTPException
from jwt.exceptions import InvalidTokenError

_ph = PasswordHasher()
SECRET = os.environ.get("AUTH_JWT_SECRET", "brandsentinel-dev-secret-key-2026")

DEMO_USERS = {
    "maya.creator": (_ph.hash("demo-maya"), ("CREATOR",)),
    "marcus.marketing": (_ph.hash("demo-marcus"), ("MARKETING_HEAD",)),
    "priya.legal": (_ph.hash("demo-priya"), ("LEGAL_COUNSEL",)),
    "rahul.brand": (_ph.hash("demo-rahul"), ("BRAND_LEAD",)),
    "sam.dual": (_ph.hash("demo-sam"), ("MARKETING_HEAD", "LEGAL_COUNSEL")),
}


def login(username: str, password: str, role: str | None = None) -> dict:
    rec = DEMO_USERS.get(username)
    if rec is None:
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    try:
        _ph.verify(rec[0], password)
    except (VerifyMismatchError, VerificationError):
        raise HTTPException(status_code=401, detail="Wrong username or password.") from None
    roles = rec[1]
    active = role if role in roles else roles[0]
    token = jwt.encode(
        {"sub": username, "role": active, "exp": int(time.time()) + 4 * 3600},
        SECRET,
        algorithm="HS256",
    )
    return {"token": token, "user": username, "role": active, "roles": list(roles)}


def current_user(authorization: str = Header(default="")) -> dict:
    try:
        token = authorization.removeprefix("Bearer ").strip()
        claims = jwt.decode(token, SECRET, algorithms=["HS256"])
        if not isinstance(claims.get("sub"), str) or not isinstance(claims.get("role"), str):
            raise InvalidTokenError("Missing subject or role.")
        return {"id": claims["sub"], "role": claims["role"]}
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Sign in to continue.") from None


def require_brand_lead(user: dict) -> dict:
    if user.get("role") != "BRAND_LEAD":
        raise HTTPException(status_code=403, detail="BRAND_LEAD role required.")
    return user
