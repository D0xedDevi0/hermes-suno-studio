#!/usr/bin/env python3
"""Render a free local draft straight from a Rhythm Reaper frame directory.

Reads <frame>/style.txt, compacts it for MusicGen (long style blocks get
truncated by the text encoder anyway), renders a short instrumental draft with
draft.py, and drops the WAV + manifest into the frame directory next to the
Suno manifest, so one folder holds the free sketch and the paid master.

MusicGen has no negative prompt: <frame>/exclude.txt is NOT used here -- those
exclusions only hold on the Suno (final) render.

Usage:
    venv/bin/python frame_draft.py --frame /opt/data/music/cold-storage --seconds 20
"""

import argparse
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser(description="Frame -> free local draft")
ap.add_argument("--frame", required=True, help="frame dir containing style.txt")
ap.add_argument("--seconds", type=int, default=20, help="draft length (cap 30)")
ap.add_argument("--seed", type=int, default=None)
ap.add_argument("--model", default="facebook/musicgen-small")
ap.add_argument("--threads", type=int, default=16)
a = ap.parse_args()

style = open(os.path.join(a.frame, "style.txt")).read().strip()
tempo = re.search(r"(\d+\s*-\s*\d+\s*BPM[^.]*\.?|~?\d{2,3}\s*BPM[^.]*\.?)", style, re.I)
body = style[:300].rsplit(". ", 1)[0] if len(style) > 300 else style
prompt = (body.rstrip(".") + "." + (" " + tempo.group(1).strip() if tempo else "")).strip()
print("prompt (%d chars): %s" % (len(prompt), prompt), flush=True)

cmd = [os.path.join(HERE, "venv", "bin", "python"), os.path.join(HERE, "draft.py"),
       "--prompt", prompt, "--seconds", str(a.seconds), "--model", a.model,
       "--threads", str(a.threads), "--out", a.frame]
if a.seed is not None:
    cmd += ["--seed", str(a.seed)]
subprocess.run(cmd, check=True)
