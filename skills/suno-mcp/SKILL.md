---
name: suno-mcp
description: Use when generating or downloading songs via Suno's MCP.
version: 1.0.0
author: D0xedDevi0
license: MIT
metadata:
  hermes:
    tags: [suno, music, mcp, oauth, audio]
    related_skills: [rhythm-reaper-operations, ai-music-production-workflow, comfyui, mcp-builder]
---

# Suno MCP — api.suno.com/mcp

Suno's official remote MCP. OAuth-only (no API key), spends the account's Suno
credits, songs land in the normal Suno library. Verified live against the real
server: 61 upstream tools.

## When to Use
- Writing, generating, extending, covering, remixing or stem-splitting a song via Suno.
- Reading or searching the Suno library, playlists or workspaces.
- Exporting a finished Suno song, or building music-video Sequences from one.
- Any time `api.suno.com/mcp` must be authored for another MCP client.

## Paths
- Client + CLI: `/opt/data/suno-mcp` (`sunolib/oauth.py`, `sunolib/mcp.py`, `suno_cli.py`, `suno`, `server.py`)
- Credentials: `/opt/data/.secrets/suno-mcp/credentials.json` (0600; 900 s access token, auto-refreshed)

## Commands
```
suno status | doctor | whoami            # doctor = handshake + upstream tool count
suno tools [--schema audio-create]       # catalog, or one full input schema
suno call <tool> --args '{"k":"v"}'     # any of the 61 tools
suno list --limit 10 | wait <id> <id> | get <id>
suno download <id> --out DIR             # spends one download credit
```

## Whole-track builder
`suno_track.py` turns a Rhythm Reaper frame into a finished track — create -> audio-wait
-> length -> extensions-create -> audio-full-song -> export -> alignment -> `manifest.json`:
```
suno_track.py --title T --style style.txt --lyrics bars.txt [--exclude E] \
  [--model v6] [--duration 180] [--out DIR] [--no-extend] [--wav] [--from-clip ID]
```
`--from-clip` resumes an interrupted run (or any existing take) without regenerating.

## Free drafts before paid finals (local CPU lane)
`/opt/data/local-lane` renders text-to-music drafts with MusicGen on CPU - no API, no
credits, offline after the first model download (~1.5 GB).
```
local-lane/venv/bin/python local-lane/frame_draft.py --frame DIR --seconds 20
```
It reads `DIR/style.txt`, compacts it for MusicGen, and drops `draft_<epoch>.wav` + a
manifest next to the Suno manifest, so one frame folder holds the free sketch and the
paid master. Measured on 16 CPU cores: **~1.7 s of compute per second of audio**
(12 s draft in 25 s wall, RTF 0.58). Output is mono 32 kHz - sketches only.
Flow: draft free locally, choose the arrangement that works, then spend Suno credits
on the final. MusicGen has no negative prompt, so a frame's `exclude.txt` applies to
the Suno render only.

## Verified economics and behaviour (measured against the live server)
- `audio-create` returns **2 songs per call and charges both** — measured at **5 credits/song**.
- `audio-extensions-create` also returns 2 takes and charges both.
- `audio-full-song` (join extension + source) **costs 0 credits** and returns a NEW clip id.
- `audio-download` costs one **monthly download credit** (separate from generation credits).
  Two failure modes to handle: `quota_exhausted` ("Monthly downloads maxed out") is
  fatal until the cycle renews, and `rate_limited` ("too many downloads at once",
  carries `retry_after_seconds`) hits back-to-back calls. Never request the same clip
  twice in a row — reuse the file you already fetched.
- Length/BPM/key come from `audio-analysis` with no download credit; it answers
  `status: processing` first, then fills `duration_s`, `bpm`, `key`.
- `audio-lyrics-alignment` returns per-word `start_s`/`end_s` — use it for captions
  and lyric videos instead of guessing timings.
- `audio-extensions-create` echoes the **source** clip in its top-level `id` while the
  new takes arrive in `clip_ids`: always take `clip_ids[0]`, never `id`.

## Sign-in (once)
`suno login` prints an authorize URL; approve it in a browser, then copy the
`?code=` out of the address bar of the page that fails to load and run
`suno auth '<full redirect URL>'`. The URL is single-use and the PKCE verifier is
stored with the pending state, so never run `suno login` twice in a row.

## Idea -> playable song
1. `audio-create` — simple mode: `description` alone. Custom mode: `lyrics` +
   `style` (+ `title`). Mixing the two modes returns 400; `instrumental: true`
   allows `description` with no lyrics.
2. **One call returns 2 songs and charges for both.** Never loop creates.
3. Poll `audio-wait` with `{"ids": [...]}` until `status` is `streaming`, then `complete`.
4. `audio-retrieve` for one clip, `library-list` for the library (cursor-paged).
5. Exporting an MP3 is only possible through `audio-download` (`confirm: true`),
   which spends a download credit; no tool exposes a free streaming URL.

## High-value tools
- `audio-extensions-create` + `audio-full-song` — build then join a longer track
- `audio-covers-create`, `audio-mashups-create`, `audio-edit`, `audio-settings`, `audio-stems-create` (stems), `audio-midi` (MIDI transcription), `audio-analysis`, `audio-listen`
- `audio-lyrics-alignment` — word-level timings, use for captions and visualizers
- `library-search`, `library-liked`, `playlists-*`, `workspaces-*`, `custom-models-list`
- `voices-list` / `voices-start` (custom voice), `speech-create`, `sounds-create`
- `image-create`, `video-create`, `visuals-*`, `sequence-*` (music-video timelines), `video-assemble`

## Pitfalls
- Upstream schemas set `additionalProperties: false`: an invented field is a 400.
  Always read the schema first — `suno tools --schema <tool>`.
- The OAuth token endpoint sits behind Cloudflare and rejects non-browser user
  agents; send a Chrome UA plus `Origin`/`Referer: https://suno.com`.
- `authorize` 302s to `suno.com/link-account`, which is the real consent screen.
- `controls`, `negative_style` and `vocal_gender` need the plan's advanced-controls
  grant (403 without it); `max_mode` only when the user asks for Max Mode by name.
- Build the production frame with the `rhythm-reaper` skill (lane, BPM, key,
  exclusions) before calling `audio-create`, and pass its style block to `style`.

## Other clients
Remote entry (Hermes handles OAuth itself):
```yaml
mcp_servers:
  suno:
    url: "https://api.suno.com/mcp"
    auth: oauth
```
Or the local stdio bridge, for any MCP client:
`python3 /opt/data/suno-mcp/server.py` → tools `suno_account`, `suno_catalog`,
`suno_call`, `suno_generate`, `suno_library`, `suno_download`; `suno_call`
reaches every upstream tool, so new Suno tools need no code change.
