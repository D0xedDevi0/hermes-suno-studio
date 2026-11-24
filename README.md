# suno-mcp — Suno's official MCP server, wired for Hermes

Backend: `https://api.suno.com/mcp` (Suno's first-party remote MCP, beta).
Auth: OAuth 2.1 + PKCE, public client via Dynamic Client Registration. No API key.
Billing: your Suno plan credits. Songs land in your normal Suno library.

## Files
- `sunolib/oauth.py` — discovery, DCR, PKCE, code exchange, refresh, token store
- `sunolib/mcp.py` — MCP Streamable-HTTP client (handshake, tools/list, tools/call)
- `suno_cli.py` + `suno.sh` — CLI (`suno ...`)
- `server.py` — MCP stdio server (exposes Suno as local tools to any MCP client)
- credentials: `/opt/data/.secrets/suno-mcp/credentials.json` (0600)

## CLI
```
suno login                  # register + print the authorize URL
suno auth '<redirect-url>'  # finish sign-in (paste the address bar)
suno status | doctor | whoami | usage
suno tools [--schema NAME]  # upstream catalog
suno call <tool> --args '{"k":"v"}'
suno list --limit 10 | get <id> | wait <id> | download <id> --out DIR
```

## Use from any MCP client
```
hermes mcp add --command "python3 /opt/data/suno-mcp/server.py" suno
```
Cursor / Claude Desktop / ChatGPT-desktop `mcpServers` entry:
```json
{"suno": {"command": "python3", "args": ["/opt/data/suno-mcp/server.py"]}}
```
Local tools exposed: `suno_account`, `suno_catalog`, `suno_call`, `suno_generate`,
`suno_library`, `suno_download`. `suno_call` reaches every upstream tool, so new
Suno tools need no code change.

## Use from Hermes as a *remote* MCP server (no local process)
```yaml
mcp_servers:
  suno:
    url: "https://api.suno.com/mcp"
    auth: oauth
```
Hermes handles discovery, DCR, PKCE, refresh itself. On a headless gateway it
prints the authorize URL and accepts the pasted redirect URL.

## Gotchas
- Access tokens live 900 s; both paths refresh automatically.
- The token endpoint is behind Cloudflare and rejects non-browser user agents:
  send a Chrome UA plus `Origin`/`Referer: https://suno.com`.
- `authorize` 302s to `suno.com/link-account`, which is the real consent page.
- `audio-download` costs one download credit; `audio-create` spends one generation
  per clip — always send an explicit clip count (this client defaults to 1).
- The loopback redirect (`http://127.0.0.1:27891/callback`) intentionally has no
  listener: you copy the code out of the address bar after approving.

## Whole-track builder (`suno_track.py`)
Turns a Rhythm Reaper frame into a finished track: create -> wait -> length ->
`audio-extensions-create` -> `audio-full-song` (join) -> export -> lyric alignment -> `manifest.json`.
```
suno_track.py --title T --style style.txt --lyrics bars.txt [--exclude E] \
  [--model v6] [--duration 180] [--out DIR] [--no-extend] [--wav] [--from-clip ID]
```
`--from-clip` resumes an interrupted run without regenerating. Works whether or not
the export step is available (length falls back to `audio-analysis`).

See `examples/frost-line/` for a complete, verified run (frame in, manifest out)
and `skills/suno-mcp/SKILL.md` for the measured economics and gotchas.

## Measured (live server)
| action | cost |
| --- | --- |
| `audio-create` | 2 songs per call, both charged (~5 credits/song) |
| `audio-extensions-create` | 2 takes, both charged |
| `audio-full-song` (join) | **0 credits**, returns a new clip id |
| `audio-download` | 1 monthly download credit (separate meter), rate-limited |
