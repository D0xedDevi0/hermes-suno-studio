# Local Music Draft Lane (`/opt/data/local-lane`)

Free, offline, CPU-only text-to-music **draft** renderer using
[MusicGen](https://huggingface.co/docs/transformers/main/en/model_doc/musicgen)
via the `transformers` library. No paid API, no credits.

## What it is / is NOT

- **IS**: a zero-cost sketch lane — try a prompt, hear a vibe, iterate cheaply.
- **IS NOT**: final quality. The paid **Suno MCP** renders the finals. Never use
  this lane's output as a shipped track.

## Install (already done on this box)

```bash
python3 -m venv /opt/data/local-lane/venv
/opt/data/local-lane/venv/bin/pip install --upgrade pip
/opt/data/local-lane/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
/opt/data/local-lane/venv/bin/pip install transformers scipy soundfile
```

First run downloads `facebook/musicgen-small` (~1.5 GB) to the HF cache.

## Run

```bash
cd /opt/data/local-lane
venv/bin/python draft.py --prompt "dark cinematic boom bap instrumental, 92 bpm, dusty vinyl drums, minor-key piano loop, deep sub bass" --seconds 15
# or read the prompt from a file:
venv/bin/python draft.py --style-file prompt.txt --seconds 10 --seed 7
```

Args: `--prompt` / `--style-file`, `--seconds` (default 15, cap 30),
`--model` (default `facebook/musicgen-small`), `--seed`, `--out`
(default `out/`), `--threads` (default 16).

Output: a 32 kHz mono 16-bit PCM WAV plus a sibling `.manifest.json` with
prompt, model, seed, `audio_seconds`, `sample_rate`, `wall_clock_seconds`, and
`real_time_factor`.

## Measured speed (this box: 16 CPU cores, 31 GB RAM, no GPU)

| seconds | wall clock (incl. load) | generation | real-time factor |
|---------|-------------------------|------------|------------------|
| 15      | 78.6 s                  | 25.4 s     | 0.19             |
| 10      | 17.5 s                  | 16.6 s     | 0.57             |

Model load is ~53 s cold (first time) and <1 s warm (weights cached). RTF is
~0.2–0.6 on CPU, so a 30 s draft takes roughly 1–2 minutes. Cost per draft is
CPU time only — no money.

## Swapping in a bigger model (GPU machine)

MusicGen scales by model size. On a machine with a GPU you can

```bash
pip install torch  # CUDA build, NOT --index-url .../cpu
venv/bin/python draft.py --model facebook/musicgen-medium --seconds 30
```

Even bigger/faster options (may need model-specific tokenizer/processor tweaks
versus the stock `AutoProcessor` path):

- `facebook/musicgen-large` — highest MusicGen quality, slowest.
- `nateraw/ACE-Step` (or `ACE-Step` variants) — higher-quality multi-instrument
  gen; swap the processor/model id the same way.

On GPU the RTF typically exceeds 1.0 (faster than real-time); on this CPU box
stick to `musicgen-small` for practical drafts.

## Notes / caveats

- Mono, 32 kHz output — fine for drafts, too lo-fi for finals.
- `transformers` logs harmless warnings about `pad_token_id`/`bos_token_id` =
  2048 (MusicGen config quirk); output is unaffected.
- Output is non-deterministic unless you pass `--seed` (plus a fixed thread
  count for reproducibility).

## Frame bridge (`frame_draft.py`)
Renders a draft straight from a Rhythm Reaper frame directory:
```
venv/bin/python frame_draft.py --frame /opt/data/music/<track> --seconds 20 [--seed N]
```
It reads `<frame>/style.txt`, compacts it to ~300 chars plus the BPM/key tail
(MusicGen's text encoder truncates long style blocks anyway), and writes
`draft_<epoch>.wav` + `.manifest.json` into the frame directory itself — so one
folder holds the free sketch and the paid Suno master side by side.
Tested on the COLD STORAGE frame: 12 s draft, 19.7 s generation, 25 s wall, RTF 0.58.

## Limits (measured, not guessed)
- Mono, 32 kHz, ~1.7 s of CPU compute per second of audio on 16 cores. A 30 s draft
  costs about 50 s; a 2-minute draft about 3.5 minutes. Fine for sketching, not for
  rendering an album overnight on this box.
- MusicGen has **no negative prompt** — a frame's `exclude.txt` cannot be enforced
  here; it applies to the Suno (final) render only.
- `musicgen-small` is the only model that runs at this speed on CPU. Swap `--model` to
  `facebook/musicgen-medium` or ACE-Step only on a GPU machine.
