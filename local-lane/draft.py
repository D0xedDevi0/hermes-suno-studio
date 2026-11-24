#!/usr/bin/env python3
"""Local CPU text-to-music draft lane.

Renders short text-to-music drafts with MusicGen (transformers). Free, offline
after first model download, no paid API. Produces sketches only -- final
quality comes from the paid Suno MCP, so this lane must never replace it.

Usage:
    venv/bin/python draft.py --prompt "dark boom bap..." --seconds 15
    venv/bin/python draft.py --style-file prompt.txt --seconds 10 --seed 7
"""

import argparse
import json
import os
import time

import scipy.io.wavfile
import torch
from transformers import AutoProcessor, MusicgenForConditionalGeneration


def parse_args():
    p = argparse.ArgumentParser(description="Local CPU MusicGen draft renderer")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--prompt", type=str, help="text prompt (mutually exclusive with --style-file)")
    src.add_argument("--style-file", type=str, help="read the prompt from this file")
    p.add_argument("--seconds", type=int, default=15, help="audio length in seconds (default 15, cap 30)")
    p.add_argument("--model", default="facebook/musicgen-small", help="HF model id (default facebook/musicgen-small)")
    p.add_argument("--seed", type=int, default=None, help="generation seed (optional)")
    p.add_argument("--out", default="/opt/data/local-lane/out", help="output dir")
    p.add_argument("--threads", type=int, default=16, help="torch CPU thread count")
    return p.parse_args()


def main():
    args = parse_args()
    if args.prompt is None and args.style_file is None:
        raise SystemExit("error: provide --prompt or --style-file")
    if args.style_file:
        with open(args.style_file) as f:
            prompt = f.read().strip()
    else:
        prompt = args.prompt.strip()
    if not prompt:
        raise SystemExit("error: prompt is empty")

    args.seconds = max(1, min(args.seconds, 30))

    torch.set_num_threads(args.threads)
    if args.seed is not None:
        torch.manual_seed(args.seed)

    t0 = time.time()
    print(f"loading model {args.model} ...", flush=True)
    processor = AutoProcessor.from_pretrained(args.model)
    model = MusicgenForConditionalGeneration.from_pretrained(args.model)
    t_load = time.time()
    print(f"model loaded in {t_load - t0:.1f}s", flush=True)

    inputs = processor(
        text=[prompt],
        padding=True,
        return_tensors="pt",
    )

    t_gen0 = time.time()
    audio_values = model.generate(
        **inputs,
        do_sample=True,
        guidance_scale=3.0,
        max_new_tokens=int(args.seconds * model.config.audio_encoder.frame_rate),
    )
    t_gen1 = time.time()

    sr = model.config.audio_encoder.sampling_rate
    audio = audio_values[0, 0].cpu().numpy()
    audio = (audio * 32767.0).astype("int16")

    os.makedirs(args.out, exist_ok=True)
    stem = f"draft_{int(time.time())}"
    wav_path = os.path.join(args.out, stem + ".wav")
    scipy.io.wavfile.write(wav_path, sr, audio)

    audio_seconds = len(audio) / sr
    wall_clock = t_gen1 - t0
    gen_only = t_gen1 - t_gen0
    rtf = audio_seconds / wall_clock

    manifest = {
        "prompt": prompt,
        "model": args.model,
        "seed": args.seed,
        "audio_seconds": round(audio_seconds, 3),
        "sample_rate": int(sr),
        "wall_clock_seconds": round(wall_clock, 3),
        "generation_seconds": round(gen_only, 3),
        "real_time_factor": round(rtf, 4),
    }
    manifest_path = os.path.join(args.out, stem + ".manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"WAV: {wav_path}")
    print(f"manifest: {manifest_path}")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
