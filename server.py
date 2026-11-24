#!/usr/bin/env python3
"""MCP stdio server exposing Suno (https://api.suno.com/mcp) as local tools.

Add to any MCP client:
  hermes mcp add --command "python3 /opt/data/suno-mcp/server.py" suno
Claude/Cursor/Desktop mcpServers entry: {"command":"python3","args":["/opt/data/suno-mcp/server.py"]}

Credentials are shared with the CLI (~/.secrets/suno-mcp); sign in once with `suno login`.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sunolib import mcp as M, oauth as O  # noqa: E402

CACHE = os.path.join(HERE, "tools-cache.json")
PROTO = "2025-06-18"
CREATE_CANDIDATES = ["audio-create", "create-audio", "create", "generate", "music-create"]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def upstream(refresh=False):
    if not refresh and os.path.exists(CACHE):
        try:
            return json.load(open(CACHE))
        except Exception:
            pass
    t = M.Session().tools()
    json.dump(t, open(CACHE, "w"), indent=1)
    return t


def txt(s):
    return {"content": [{"type": "text", "text": s if isinstance(s, str) else json.dumps(s, indent=2, ensure_ascii=False)}]}


def err(s):
    return {"content": [{"type": "text", "text": s}], "isError": True}


def tool_defs():
    return [
        {"name": "suno_account",
         "description": "Signed-in Suno profile plus plan, credits and available models.",
         "inputSchema": {"type": "object", "properties": {}},
         "annotations": {"readOnlyHint": True}},
        {"name": "suno_catalog",
         "description": "List every tool the Suno MCP server exposes with its description (create/extend/cover/mashup/lyrics/visuals/library/downloads).",
         "inputSchema": {"type": "object", "properties": {"refresh": {"type": "boolean"}}},
         "annotations": {"readOnlyHint": True}},
        {"name": "suno_call",
         "description": "Call any Suno MCP tool by name with its arguments; use suno_catalog for names and schemas. The full upstream catalog is available this way.",
         "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "arguments": {"type": "object"}}, "required": ["name"]}},
        {"name": "suno_generate",
         "description": "Create a song. Spends Suno credits (one per clip). Returns clip ids; poll with suno_call on the library/wait tool.",
         "inputSchema": {"type": "object", "properties": {
             "prompt": {"type": "string", "description": "What the song should be about (becomes lyrics/title unless given)"},
             "style": {"type": "string", "description": "Style tags, e.g. 'boom bap, 90 bpm, dusty vinyl, male rap'"},
             "lyrics": {"type": "string"}, "title": {"type": "string"},
             "instrumental": {"type": "boolean"},
             "model": {"type": "string", "description": "v6-mini | v6 | v6-wild (default: your plan default)"},
             "duration": {"type": "integer", "description": "15-360 seconds"}}, "required": []}},
        {"name": "suno_library",
         "description": "Recent songs in the Suno library (id, title, style, audio url).",
         "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
         "annotations": {"readOnlyHint": True}},
        {"name": "suno_download",
         "description": "Resolve a clip id to a downloadable MP3 URL. Costs one download credit.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "confirm": {"type": "boolean"}}, "required": ["id"]}},
    ]


def call_upstream(name, args, s=None):
    s = s or M.Session()
    d, note = M.content_value(s.call(name, args))
    return d if d is not None else (note or "(empty result)")


ALIASES = {
    "prompt": ["prompt", "description", "gpt_description_prompt", "idea", "subject"],
    "style": ["style", "tags", "style_tags", "styles"],
    "lyrics": ["lyrics", "lyric", "custom_lyrics", "text"],
    "title": ["title", "name"],
    "instrumental": ["instrumental", "make_instrumental", "is_instrumental"],
    "duration": ["duration", "length", "seconds", "duration_seconds"],
}


def map_args(schema, want):
    props = (schema or {}).get("properties") or {}
    out = {}
    for k, v in want.items():
        if v is None or v is False:
            continue
        for cand in ALIASES.get(k, [k]):
            if cand in props:
                out[cand] = v
                break
    return out


def dispatch(name, args, session):
    tools = upstream()
    by_name = {t["name"]: t for t in tools}
    if name == "suno_account":
        for cand in ("usage", "account-usage", "whoami", "account-whoami", "profile-get"):
            if cand in by_name:
                return call_upstream(cand, {}, session)
        return err("no account tool upstream; found: %s" % ", ".join(sorted(by_name)))
    if name == "suno_catalog":
        if args.get("refresh"):
            tools = upstream(True)
        return [{"name": t["name"], "description": (t.get("description") or "").strip()[:220]} for t in tools]
    if name == "suno_call":
        if not args.get("name"):
            return err("suno_call needs 'name'")
        return call_upstream(args["name"], args.get("arguments") or {}, session)
    if name == "suno_generate":
        cand = next((c for c in CREATE_CANDIDATES if c in by_name), None)
        if not cand:
            return err("no create tool upstream; found: %s" % ", ".join(sorted(by_name)))
        mapped = map_args(by_name[cand].get("inputSchema"), args)
        if not mapped:
            return err("no argument matched %s's schema: %s" % (cand, list(by_name[cand].get("inputSchema", {}).get("properties", {}))))
        return call_upstream(cand, mapped, session)
    if name == "suno_library":
        for cand in ("library-list", "list", "clips-list"):
            if cand in by_name:
                return call_upstream(cand, {"limit": int(args.get("limit") or 10)}, session)
        return err("no library tool upstream")
    if name == "suno_download":
        d = call_upstream("audio-download", {"id": args["id"], "confirm": bool(args.get("confirm", True))}, session)
        return d
    return err("unknown tool %s" % name)


def main():
    session = M.Session()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        mid, method = req.get("id"), req.get("method")
        if mid is None:
            continue
        try:
            if method == "initialize":
                res = {"protocolVersion": PROTO,
                       "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": {"name": "suno-mcp", "version": "1.0.0"}}
            elif method == "tools/list":
                res = {"tools": tool_defs()}
            elif method == "tools/call":
                p = req.get("params") or {}
                got = dispatch(p.get("name"), p.get("arguments") or {}, session)
                res = got if isinstance(got, dict) and "content" in got else txt(got)
            elif method == "resources/list":
                res = {"resources": []}
            elif method == "prompts/list":
                res = {"prompts": []}
            elif method == "ping":
                res = {}
            else:
                print(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}), flush=True)
                continue
            print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}, ensure_ascii=False), flush=True)
        except Exception as e:
            print(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": "%s: %s" % (type(e).__name__, e)}}), flush=True)


if __name__ == "__main__":
    main()
