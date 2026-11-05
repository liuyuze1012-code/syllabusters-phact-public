"""Accounts: sign up / log in with Amazon Cognito (docs/contracts-userdata.md).

Two session modes:
  PHACT_AUTH_MODE=jwt     (on AWS) API Gateway's Cognito JWT authorizer verifies the token BEFORE Lambda runs;
                          we read the verified claims from the request context. Login returns the ID token,
                          which the page sends as `Authorization: Bearer …`.
  cookie (default)        (local) a signed, HTTP-only session cookie.
Inside the async worker the user comes from the job record, set through a context variable that no HTTP
request can reach.

Cognito stores and checks passwords; PHACT never sees a stored password. After login PHACT keeps only
{sub, email, name, role, exp} in an HMAC-signed, HTTP-only cookie, so no session table or server memory
is needed (works the same on EC2 or Lambda).
PHACT_AUTH=1 turns accounts on. Off (local default): one implicit local user with every role.
"""

import base64
import contextvars
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

import boto3
from fastapi import HTTPException, Request

_ids_file = Path(__file__).with_name("userdb_ids.json")
_ids = json.loads(_ids_file.read_text()) if _ids_file.exists() else {}
REGION = os.getenv("AWS_REGION", _ids.get("region", "us-west-2"))
POOL_ID = os.getenv("USER_POOL_ID", _ids.get("user_pool_id", ""))
CLIENT_ID = os.getenv("USER_POOL_CLIENT_ID", _ids.get("client_id", ""))
COOKIE = "phact_session"
TTL_S = 3600  # sign-in lasts 1 hour, the same as Cognito's ID token (Nov 5 requirement)
# ASPPH's spec names the groups `faculty` and `aspph-admin`; `aspph-staff` (our first name) still counts as admin.
ROLES = ("aspph-admin", "school-admin", "faculty")  # highest first; school-admin = a university admin
ALIASES = {"aspph-staff": "aspph-admin"}
LOCAL_USER = {"sub": "local", "email": "local@this-computer", "name": "You (local)", "role": "aspph-admin", "university_id": ""}
# Local testing only (accounts off): PHACT_LOCAL_UNI_ADMIN=westbridge makes "you" that university's admin
if os.getenv("PHACT_LOCAL_UNI_ADMIN"):
    LOCAL_USER = {**LOCAL_USER, "name": "You (local university admin)", "role": "school-admin", "university_id": os.environ["PHACT_LOCAL_UNI_ADMIN"]}
UNI_ATTR = "custom:university_id"  # readable in the ID token, never writable by the user (see setup_universities.py)
JOB_USER: contextvars.ContextVar = contextvars.ContextVar("job_user", default=None)  # set only by the worker


def enabled() -> bool:
    return os.getenv("PHACT_AUTH", "0") == "1"


def jwt_mode() -> bool:
    return os.getenv("PHACT_AUTH_MODE", "cookie") == "jwt"


def claims_user(claims: dict) -> dict | None:
    """The user from claims API Gateway already verified. HTTP API passes list claims as "[a b]"."""
    if not claims or not claims.get("sub"):
        return None
    groups = claims.get("cognito:groups", [])
    if isinstance(groups, str):
        groups = groups.strip("[]").replace(",", " ").split()
    return {"sub": claims["sub"], "email": claims.get("email", ""), "name": claims.get("name", ""), "role": _role(groups),
            "university_id": claims.get(UNI_ATTR, "")}


def request_user(request) -> dict | None:
    """Who is calling, or None. The worker's user wins; then API Gateway's verified claims; then the cookie."""
    if (u := JOB_USER.get()) is not None:
        return u
    if jwt_mode():
        ev = request.scope.get("aws.event") or {}
        auth = (ev.get("requestContext") or {}).get("authorizer") or {}
        return claims_user((auth.get("jwt") or {}).get("claims") or auth.get("claims") or {})
    return read_token(request.cookies.get(COOKIE, ""))


def _secret() -> bytes:
    if os.getenv("PHACT_SECRET"):
        return os.environ["PHACT_SECRET"].encode()
    f = Path(__file__).with_name(".uploads") / "session_secret"  # local only; on AWS set PHACT_SECRET
    if not f.exists():
        f.parent.mkdir(exist_ok=True)
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip().encode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_token(user: dict) -> str:
    payload = _b64(json.dumps({**user, "exp": int(time.time()) + TTL_S}).encode())
    sig = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str) -> dict | None:
    try:
        payload, sig = token.split(".")
        good = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return data if data.get("exp", 0) > time.time() else None
    except Exception:  # noqa: BLE001
        return None


def current_user(request: Request) -> dict:
    """The signed-in user, from the cookie only. 401 if missing, tampered with or expired."""
    if not enabled():
        return JOB_USER.get() or LOCAL_USER
    user = request_user(request)
    if not user:
        raise HTTPException(401, "Please log in.")
    return user


def require_role(user: dict, role: str) -> None:
    """Call at the top of every role-restricted route. Hiding a button is not security."""
    have, need = ALIASES.get(user.get("role"), user.get("role", "faculty")), ALIASES.get(role, role)
    if have not in ROLES or ROLES.index(have) > ROLES.index(need):
        raise HTTPException(403, "Your account doesn't have access to this page.")


# ---------- Cognito ----------
def _cog():
    return boto3.client("cognito-idp", region_name=REGION)


def _claims(id_token: str) -> dict:
    """Read the ID token Cognito just sent us over TLS (we asked for it directly, so no signature check
    is needed here; a token from anywhere else must be verified against Cognito's keys)."""
    part = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def _role(groups: list[str]) -> str:
    groups = [ALIASES.get(g, g) for g in groups]
    return next((r for r in ROLES if r in groups), "faculty")


def login(email: str, password: str) -> dict:
    try:
        r = _cog().initiate_auth(ClientId=CLIENT_ID, AuthFlow="USER_PASSWORD_AUTH",
                                 AuthParameters={"USERNAME": email.strip().lower(), "PASSWORD": password})
    except _cog().exceptions.NotAuthorizedException:
        raise HTTPException(401, "Wrong email or password.")
    except _cog().exceptions.UserNotFoundException:
        raise HTTPException(401, "Wrong email or password.")
    if "AuthenticationResult" not in r:  # e.g. a forced password change for admin-created users
        raise HTTPException(401, f"This account needs an extra step ({r.get('ChallengeName', 'unknown')}).")
    res = r["AuthenticationResult"]
    c = _claims(res["IdToken"])
    user = {"sub": c["sub"], "email": c.get("email", email), "name": c.get("name", ""), "role": _role(c.get("cognito:groups", [])),
            "university_id": c.get(UNI_ATTR, "")}
    # In JWT mode the page keeps the ID token (API Gateway verifies it on every call); never logged or stored server-side.
    return {**user, "_id_token": res["IdToken"], "_expires_in": res.get("ExpiresIn", 3600)}


def signup(email: str, password: str, name: str, role: str = "faculty", university_id: str = "") -> dict:
    """Self sign-up creates a professor account. For the demo it's confirmed immediately (no email code);
    production would keep email verification on, or invite-only accounts."""
    email = email.strip().lower()
    cog = _cog()
    try:
        cog.sign_up(ClientId=CLIENT_ID, Username=email, Password=password,
                    UserAttributes=[{"Name": "email", "Value": email}, {"Name": "name", "Value": name[:80]}])
    except cog.exceptions.UsernameExistsException:
        raise HTTPException(409, "An account with this email already exists. Log in instead.")
    except cog.exceptions.InvalidPasswordException as e:
        raise HTTPException(400, "Password too weak: " + str(e).split(":")[-1].strip())
    except cog.exceptions.InvalidParameterException as e:
        raise HTTPException(400, str(e).split(":")[-1].strip())
    cog.admin_confirm_sign_up(UserPoolId=POOL_ID, Username=email)
    cog.admin_update_user_attributes(UserPoolId=POOL_ID, Username=email,  # admin API: the only way university_id is set
                                     UserAttributes=[{"Name": "email_verified", "Value": "true"},
                                                     *([{"Name": UNI_ATTR, "Value": university_id}] if university_id else [])])
    cog.admin_add_user_to_group(UserPoolId=POOL_ID, Username=email, GroupName=role if role in ROLES else "faculty")
    return login(email, password)
