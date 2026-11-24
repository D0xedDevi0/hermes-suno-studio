#!/usr/bin/env python3
"""suno - CLI for Suno's official MCP server (https://api.suno.com/mcp).

  suno login                # register client, print the authorize URL
  suno auth <url-or-code>   # finish sign-in with the pasted redirect URL
  suno status|whoami|usage|tools|doctor
  suno call <tool> --args '{"k":"v"}'
  suno list [--limit N] | get <id> | wait <id> | download <id> --out DIR
"""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sunolib import mcp as M, oauth as O  # noqa: E402

DEFAULT_REDIRECT = "http://127.0.0.1:27891/callback"
WHOAMI_CANDIDATES = ["whoami", "account-whoami", "profile-get", "account-get"]


def out(obj):
    if isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, indent=2, ensure_ascii=False))


def pick_tool(tools, candidates, fallback=None):
    names = {t["name"] for t in tools}
    for c in candidates:
        if c in names:
            return c
    return fallback


def cmd_login(a):
    meta = O.discover()
    c = O.load()
    if a.redirect_uri:
        c["redirect_uri"] = a.redirect_uri
    c.setdefault("redirect_uri", DEFAULT_REDIRECT)
    if not c.get("client_id") or a.reregister:
        reg = O.register(c["redirect_uri"], meta)
        c["client_id"] = reg["client_id"]
        c["registered_at"] = int(time.time())
        print("registered public client: %s" % c["client_id"], file=sys.stderr)
    verifier, challenge = O.pkce()
    state = O.pkce()[0][:32]
    c["pending"] = {"verifier": verifier, "state": state, "started": int(time.time())}
    O.save(c)
    url = O.authorize_url(c["client_id"], c["redirect_uri"], challenge, state)
    print("SIGN IN: open this URL, approve, then copy the address bar you land on\n")
    print(url)
    print("\n(that last page will fail to load - the code is in its URL)")
    print("then run:  suno auth '<paste the whole redirect URL>'")


def cmd_auth(a):
    c = O.load()
    pend = c.get("pending") or {}
    if not pend.get("verifier"):
        print("no sign-in in progress - run: suno login", file=sys.stderr)
        return 1
    raw = a.input.strip()
    if "code=" in raw:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
        got_state = (qs.get("state") or [""])[0]
        code = (qs.get("code") or [""])[0]
        if pend.get("state") and got_state and got_state != pend["state"]:
            print("WARNING: state mismatch", file=sys.stderr)
    else:
        code = raw
    if not code:
        print("no ?code= found in that input", file=sys.stderr)
        return 1
    tok = O.exchange(c["client_id"], code, pend["verifier"], c["redirect_uri"])
    c.pop("pending", None)
    O.store_tokens(c, tok)
    print("signed in. scope=%s expires_in=%ss" % (tok.get("scope"), tok.get("expires_in")))
    return 0


def cmd_status(a):
    c = O.load()
    out({
        "home": O.HOME,
        "signed_in": bool(c.get("access_token")),
        "client_id": c.get("client_id"),
        "redirect_uri": c.get("redirect_uri"),
        "scope": c.get("scope"),
        "expires_in_s": int(float(c.get("expires_at", 0)) - time.time()),
        "has_refresh": bool(c.get("refresh_token")),
        "pending_login": bool((c.get("pending") or {}).get("verifier")),
    })


def cmd_whoami(a):
    s = M.Session()
    tools = s.tools()
    name = pick_tool(tools, WHOAMI_CANDIDATES)
    if not name:
        print("no whoami tool. available: %s" % ", ".join(sorted(t["name"] for t in tools)))
        return 1
    d, note = M.content_value(s.call(name))
    out(d if d is not None else note)


def cmd_usage(a):
    d, note = M.quick(a.tool or "usage")
    out(d if d is not None else note)


def cmd_tools(a):
    tools = M.Session().tools()
    if a.schema:
        for t in tools:
            if t["name"] == a.schema:
                out(t)
                return 0
        print("no tool named %s" % a.schema, file=sys.stderr)
        return 1
    for t in tools:
        desc = (t.get("description") or "").strip().replace("\n", " ")
        print("%-34s %s" % (t["name"], desc[:88]))
    print("\n%d tools" % len(tools))


def cmd_call(a):
    d, note = M.quick(a.tool, json.loads(a.args) if a.args else {})
    out(d if d is not None else note)


def cmd_list(a):
    d, note = M.quick(a.tool or "library-list", {"limit": a.limit})
    out(d if d is not None else note)


def cmd_get(a):
    d, note = M.quick(a.tool or "library-get", {"id": a.id})
    out(d if d is not None else note)


def cmd_wait(a):
    d, note = M.quick(a.tool or "library-wait", {"ids": a.ids})
    out(d if d is not None else note)


def cmd_download(a):
    d, note = M.quick("audio-download", {"id": a.id, "confirm": True})
    out(d if d is not None else note)
    url = None
    if isinstance(d, dict):
        url = d.get("url") or d.get("audio_url") or (d.get("data") or {}).get("url")
    if url and a.out:
        os.makedirs(a.out, exist_ok=True)
        path = os.path.join(a.out, "%s.mp3" % a.id)
        urllib.request.urlretrieve(url, path)
        print("saved %s" % path)


def cmd_doctor(a):
    rep = {"credentials": O.CRED, "exists": os.path.exists(O.CRED)}
    try:
        c = O.load()
        rep["signed_in"] = bool(c.get("access_token"))
        if rep["signed_in"]:
            s = M.Session()
            rep["server"] = s.open().get("serverInfo")
            rep["session_id"] = bool(s.sid)
            rep["tool_count"] = len(s.tools())
    except Exception as e:
        rep["error"] = str(e)
    out(rep)
    return 0 if rep.get("tool_count") else 1


def main():
    p = argparse.ArgumentParser(prog="suno", description="Suno MCP CLI")
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("login"); sp.add_argument("--redirect-uri"); sp.add_argument("--reregister", action="store_true"); sp.set_defaults(f=cmd_login)
    sp = sub.add_parser("auth"); sp.add_argument("input"); sp.set_defaults(f=cmd_auth)
    sub.add_parser("status").set_defaults(f=cmd_status)
    sub.add_parser("whoami").set_defaults(f=cmd_whoami)
    sp = sub.add_parser("usage"); sp.add_argument("--tool"); sp.set_defaults(f=cmd_usage)
    sp = sub.add_parser("tools"); sp.add_argument("--schema", metavar="TOOL"); sp.set_defaults(f=cmd_tools)
    sp = sub.add_parser("call"); sp.add_argument("tool"); sp.add_argument("--args"); sp.set_defaults(f=cmd_call)
    sp = sub.add_parser("list"); sp.add_argument("--limit", type=int, default=10); sp.add_argument("--tool"); sp.set_defaults(f=cmd_list)
    sp = sub.add_parser("get"); sp.add_argument("id"); sp.add_argument("--tool"); sp.set_defaults(f=cmd_get)
    sp = sub.add_parser("wait"); sp.add_argument("ids", nargs="+"); sp.add_argument("--tool"); sp.set_defaults(f=cmd_wait)
    sp = sub.add_parser("download"); sp.add_argument("id"); sp.add_argument("--out"); sp.set_defaults(f=cmd_download)
    sub.add_parser("doctor").set_defaults(f=cmd_doctor)
    a = p.parse_args()
    if not getattr(a, "f", None):
        p.print_help()
        return 2
    return a.f(a) or 0


if __name__ == "__main__":
    sys.exit(main())
