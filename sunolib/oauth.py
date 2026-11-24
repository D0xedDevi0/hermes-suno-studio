"""Suno MCP OAuth 2.1 (PKCE public client) + token store.

Flow: DCR-register a public client -> authorize (user approves in a browser)
-> exchange the code from the redirect URL -> store tokens (0600) -> auto-refresh.
The token endpoint sits behind Cloudflare and rejects non-browser UAs, so every
request carries a Chrome UA plus Origin/Referer.
"""
from __future__ import annotations
import base64, hashlib, json, os, secrets, time, urllib.error, urllib.parse, urllib.request

RESOURCE = "https://api.suno.com/mcp"
AS_BASE = "https://studio-api-prod.suno.com/api/v2/external/oauth"
SCOPES = ["api:v0", "credits:spend", "download", "library:read", "library:search",
          "library:write", "offline_access", "profile:read"]
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
HOME = os.environ.get("SUNO_MCP_HOME", "/opt/data/.secrets/suno-mcp")
CRED = os.path.join(HOME, "credentials.json")


def _req(url, data=None, headers=None, method=None, form=False):
    h = {"User-Agent": UA, "Accept": "application/json",
         "Origin": "https://suno.com", "Referer": "https://suno.com/"}
    body = None
    if data is not None:
        if form:
            h["Content-Type"] = "application/x-www-form-urlencoded"
            body = urllib.parse.urlencode(data).encode()
        else:
            h["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
    h.update(headers or {})
    r = urllib.request.Request(url, data=body, headers=h,
                               method=method or ("POST" if body is not None else "GET"))
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read().decode(errors="replace")
            return resp.status, _maybe_json(raw), dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        return e.code, _maybe_json(raw), dict(e.headers)


def _maybe_json(raw):
    s = raw.strip()
    if s.startswith("{") or s.startswith("["):
        try:
            return json.loads(s)
        except Exception:
            pass
    return raw[:600]


def discover():
    p = os.path.join(HOME, "as.json")
    if os.path.exists(p):
        try:
            return json.load(open(p))
        except Exception:
            pass
    st, d, _ = _req(AS_BASE + "/.well-known/oauth-authorization-server")
    if st != 200 or not isinstance(d, dict):
        raise RuntimeError("OAuth discovery failed: %s %s" % (st, d))
    os.makedirs(HOME, exist_ok=True)
    os.chmod(HOME, 0o700)
    json.dump(d, open(p, "w"), indent=2)
    return d


def load():
    try:
        return json.load(open(CRED))
    except Exception:
        return {}


def save(c):
    os.makedirs(HOME, exist_ok=True)
    os.chmod(HOME, 0o700)
    tmp = CRED + ".tmp"
    with open(tmp, "w") as f:
        json.dump(c, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CRED)
    return c


def pkce():
    v = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    c = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    return v, c


def register(redirect_uri, as_meta=None):
    """RFC 7591 dynamic client registration (public client, no secret)."""
    meta = as_meta or discover()
    payload = {
        "client_name": "Hermes Agent (D0xedDev)",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": " ".join(SCOPES),
    }
    st, d, _ = _req(meta["registration_endpoint"], payload)
    if st not in (200, 201) or not isinstance(d, dict) or "client_id" not in d:
        raise RuntimeError("DCR failed: %s %s" % (st, d))
    return d


def authorize_url(client_id, redirect_uri, challenge, state, scopes=None):
    meta = discover()
    q = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes or SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": RESOURCE,
    }
    return meta["authorization_endpoint"] + "?" + urllib.parse.urlencode(q)


def exchange(client_id, code, verifier, redirect_uri, as_meta=None):
    meta = as_meta or discover()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": RESOURCE,
    }
    st, d, _ = _req(meta["token_endpoint"], data, form=True)
    if st != 200 or not isinstance(d, dict) or "access_token" not in d:
        raise RuntimeError("token exchange failed: %s %s" % (st, d))
    return d


def refresh(client_id, refresh_token, as_meta=None):
    meta = as_meta or discover()
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token,
            "client_id": client_id, "resource": RESOURCE}
    st, d, _ = _req(meta["token_endpoint"], data, form=True)
    if st != 200 or not isinstance(d, dict) or "access_token" not in d:
        raise RuntimeError("refresh failed: %s %s" % (st, d))
    return d


def store_tokens(c, tok):
    c["access_token"] = tok["access_token"]
    if tok.get("refresh_token"):
        c["refresh_token"] = tok["refresh_token"]
    c["expires_at"] = time.time() + int(tok.get("expires_in", 900))
    c["token_type"] = tok.get("token_type", "Bearer")
    if tok.get("scope"):
        c["scope"] = tok["scope"]
    return save(c)


def access_token(c=None, skew=60):
    """Fresh bearer token, refreshing when it is inside the skew window."""
    c = c or load()
    if not c.get("access_token"):
        raise RuntimeError("not signed in — run: suno login")
    if time.time() >= float(c.get("expires_at", 0)) - skew:
        if not c.get("refresh_token"):
            raise RuntimeError("token expired and no refresh_token — run: suno login")
        tok = refresh(c["client_id"], c["refresh_token"])
        c = store_tokens(c, tok)
        c["_refreshed"] = True
    return c["access_token"]
