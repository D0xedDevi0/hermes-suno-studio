"""Minimal MCP Streamable-HTTP client for https://api.suno.com/mcp.

Handles: initialize handshake (session id capture), notifications/initialized,
tools/list, tools/call, SSE or JSON responses, and one automatic token refresh
on 401.
"""
from __future__ import annotations
import json, urllib.error, urllib.request

from . import oauth as O

PROTO = "2025-06-18"
UA = O.UA


def _post(payload, token, session=None, timeout=180):
    h = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": UA,
        "MCP-Protocol-Version": PROTO,
    }
    if session:
        h["mcp-session-id"] = session
    r = urllib.request.Request(O.RESOURCE, data=json.dumps(payload).encode(), headers=h, method="POST")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode(errors="replace")
            return resp.status, raw, dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace"), dict(e.headers)


def _decode(raw, want_id=None):
    """Return the JSON-RPC message from a JSON or SSE body."""
    s = raw.strip()
    if not s:
        return None
    if s.startswith("{"):
        try:
            return json.loads(s)
        except Exception:
            return None
    msgs = []
    for line in s.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            body = line[5:].strip()
            if body:
                try:
                    msgs.append(json.loads(body))
                except Exception:
                    pass
    for m in msgs:
        if want_id is None or m.get("id") == want_id:
            return m
    return msgs[-1] if msgs else None


class Session:
    """One MCP session: initialize once, then call tools."""

    def __init__(self):
        self.sid = None
        self.info = None

    def _call(self, payload, want_id, retry=True):
        cred = O.load()
        token = O.access_token(cred)
        st, raw, hdrs = _post(payload, token, self.sid)
        if st == 401 and retry:
            c = O.load()
            if c.get("refresh_token"):
                O.store_tokens(c, O.refresh(c["client_id"], c["refresh_token"]))
                return self._call(payload, want_id, retry=False)
            raise RuntimeError("401 from Suno MCP and no refresh_token — run: suno login")
        if st not in (200, 202):
            raise RuntimeError("MCP HTTP %s: %s" % (st, raw[:300]))
        if not self.sid:
            for k, v in hdrs.items():
                if k.lower() == "mcp-session-id":
                    self.sid = v
        msg = _decode(raw, want_id)
        if msg and msg.get("error"):
            err = msg["error"]
            raise RuntimeError("MCP error %s: %s" % (err.get("code"), err.get("message")))
        return msg

    def open(self):
        msg = self._call({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTO, "capabilities": {},
                       "clientInfo": {"name": "hermes-suno", "version": "1.0.0"}}}, 1)
        self.info = (msg or {}).get("result", {})
        try:
            _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, O.access_token(), self.sid)
        except Exception:
            pass
        return self.info

    def ensure(self):
        if not self.sid:
            self.open()
        return self

    def tools(self):
        self.ensure()
        msg = self._call({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, 2)
        return ((msg or {}).get("result") or {}).get("tools", [])

    def call(self, name, args=None, timeout=240):
        self.ensure()
        msg = self._call({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                          "params": {"name": name, "arguments": args or {}}}, 3)
        return (msg or {}).get("result") or {}


def content_value(res):
    """Best-effort decode of an MCP tool result into (data, human_text)."""
    parts = []
    for blk in res.get("content") or []:
        if blk.get("type") == "text":
            parts.append(blk.get("text", ""))
    data, note = None, None
    for p in parts:
        s = p.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                data = json.loads(s)
                continue
            except Exception:
                pass
        note = (note + "\n" + p) if note else p
    if res.get("structuredContent"):
        data = res["structuredContent"]
    return data, note


def quick(name, args=None):
    """One-shot tool call in a fresh session."""
    return content_value(Session().call(name, args))
