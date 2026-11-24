#!/usr/bin/env python3
"""suno_track.py - Rhythm Reaper frame -> finished, exported Suno track.

  suno_track.py --title T --style style.txt --lyrics bars.txt [--exclude E]
                [--model v6] [--duration 180] [--out DIR] [--no-extend] [--wav]

Flow: audio-create -> audio-wait -> export the take for exact length ->
audio-extensions-create -> audio-full-song (join) -> audio-download ->
audio-lyrics-alignment -> manifest.json
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sunolib import mcp as M  # noqa: E402

PLAYABLE = ("streaming", "complete")


def read(path):
    with open(path) as f:
        return f.read().strip()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "track"


def usage(s):
    d, _ = M.content_value(s.call("account-usage"))
    a = (d or {}).get("suno_account") or {}
    return a.get("credits_remaining"), a.get("download_credits_remaining")


def wait_ready(s, ids, until="playable", tries=45, pause=7, label=""):
    clips = []
    for i in range(tries):
        d, _ = M.content_value(s.call("audio-wait", {"ids": ids, "until": until}))
        clips = (d or {}).get("clips") or []
        states = [c.get("status") for c in clips]
        print("  %s poll %02d %s" % (label, i, states), flush=True)
        if clips and all(c.get("status") in PLAYABLE for c in clips):
            return clips
        if any(c.get("status") == "error" for c in clips):
            raise RuntimeError("upstream error: %s" % json.dumps([c.get("error") for c in clips]))
        time.sleep(pause)
    return clips


def mp3_of(s, cid, fmt="mp3", tries=4):
    """-> (url, error). Export is quota-metered and rate-limited; failure is not fatal."""
    d = None
    for i in range(tries):
        d, _ = M.content_value(s.call("audio-download", {"id": cid, "confirm": True, "format": fmt}))
        if isinstance(d, dict) and d.get("url"):
            return d["url"], None
        if isinstance(d, dict) and d.get("reason") == "rate_limited":
            time.sleep(float(d.get("retry_after_seconds") or 3) + 2)
            continue
        break
    return None, json.dumps(d)[:200] if d else "no response"


def analysis_wait(s, cid, tries=12, pause=10):
    d = {}
    for _ in range(tries):
        d, _ = M.content_value(s.call("audio-analysis", {"id": cid}))
        if isinstance(d, dict) and d.get("duration_s"):
            return d
        time.sleep(pause)
    return d if isinstance(d, dict) else {}


def duration_of(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", path], capture_output=True, text=True).stdout
        return float(out.strip())
    except Exception:
        return None


def fetch(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        print("  reuse %s" % path)
        return path
    urllib.request.urlretrieve(url, path)
    print("  saved %s (%.0f KB)" % (path, os.path.getsize(path) / 1024))
    return path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--style", required=True, help="style file or inline text")
    p.add_argument("--lyrics", required=True, help="lyrics file or inline text")
    p.add_argument("--exclude", help="Exclude Styles line -> negative_style")
    p.add_argument("--model", help="v6 | v6-mini | v6-wild")
    p.add_argument("--duration", type=int, default=180, help="target total seconds")
    p.add_argument("--out", default=".")
    p.add_argument("--no-extend", action="store_true")
    p.add_argument("--wav", action="store_true")
    p.add_argument("--instrumental", action="store_true")
    p.add_argument("--from-clip", help="skip creation, resume from an existing clip id")
    a = p.parse_args()

    style = read(a.style) if os.path.exists(a.style) else a.style
    lyrics = read(a.lyrics) if os.path.exists(a.lyrics) else a.lyrics
    s = M.Session()
    os.makedirs(a.out, exist_ok=True)
    name = slug(a.title)
    c0 = usage(s)
    print("credits before: %s" % (c0,))

    args = {"title": a.title, "style": style, "duration": a.duration, "duration_strict": False}
    if lyrics:
        args["lyrics"] = lyrics
    if a.model:
        args["model"] = a.model
    if a.exclude:
        args["negative_style"] = a.exclude
    if a.instrumental:
        args["instrumental"] = True
    if a.from_clip:
        ids, cid = [a.from_clip], a.from_clip
        print("-> resuming from existing clip %s" % cid)
    else:
        print("-> audio-create (2 songs charged per call)")
        d, note = M.content_value(s.call("audio-create", args))
        ids = (d or {}).get("clip_ids") or ([d["id"]] if isinstance(d, dict) and d.get("id") else [])
        if not ids:
            raise SystemExit("create returned nothing usable: %s / %s" % (json.dumps(d)[:300], note))
        print("   clip_ids: %s" % ids)
        clips = wait_ready(s, ids, label="create")
        cid = clips[0]["id"]
    print("   take: %s" % cid)

    first = os.path.join(a.out, "%s-take.mp3" % name)
    url, err = mp3_of(s, cid)
    dur = 0.0
    if url:
        fetch(url, first)
        dur = duration_of(first) or 0
    else:
        print("   export unavailable: %s" % err)
        an = analysis_wait(s, cid)
        dur = float(an.get("duration_s") or 0)
        print("   length from analysis: %.1fs bpm=%s key=%s" % (dur, an.get("bpm"), an.get("key")))
    print("   take length: %.1fs" % dur)

    final_id = cid
    if not a.no_extend and dur and dur < a.duration - 15:
        ext_seconds = int(min(360, a.duration - dur + 5))
        continue_at = round(max(5.0, dur - 4), 1)
        print("-> audio-extensions-create (continue_at=%.1f, duration=%d)" % (continue_at, ext_seconds))
        e, _ = M.content_value(s.call("audio-extensions-create", {
            "id": cid, "continue_at": continue_at, "duration": ext_seconds,
            "style": style, "title": a.title}))
        eid = ((e or {}).get("clip_ids") or [None])[0] or (e or {}).get("id")
        if not eid:
            raise SystemExit("extension returned no id: %s" % json.dumps(e)[:300])
        print("   extension id: %s" % eid)
        wait_ready(s, [eid], label="extend")
        print("-> audio-full-song (join extension + source)")
        f, _ = M.content_value(s.call("audio-full-song", {"id": eid}))
        fid = ((f or {}).get("clip_ids") or [None])[0] or (f or {}).get("id")
        if fid:
            print("   full song id: %s status=%s" % (fid, (f or {}).get("status")))
            wait_ready(s, [fid], label="join")
            final_id = fid
        else:
            print("   join returned no id, staying on the extension: %s" % json.dumps(f)[:200])

    final = os.path.join(a.out, "%s.mp3" % name)
    if final_id == cid and os.path.exists(first) and os.path.getsize(first) > 10000:
        url, dl_err = first, None          # same clip as the take: reuse, do not re-request
    else:
        url, dl_err = mp3_of(s, final_id)
    if url:
        fetch(url, final)
        fdur = duration_of(final)
    else:
        fdur = float((analysis_wait(s, final_id) or {}).get("duration_s") or 0)
        print("   export unavailable: %s" % dl_err)
    print("   final length: %.1fs -> %s" % (fdur or 0, final if url else "(no local file)"))
    if a.wav and url:
        wurl, _ = mp3_of(s, final_id, "wav")
        if wurl:
            fetch(wurl, os.path.join(a.out, "%s.wav" % name))

    al, _ = M.content_value(s.call("audio-lyrics-alignment", {"id": final_id}))
    if al:
        json.dump(al, open(os.path.join(a.out, "%s.alignment.json" % name), "w"), indent=1)
        print("   alignment -> %s.alignment.json" % name)

    c1 = usage(s)
    man = {"title": a.title, "slug": name, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "model": a.model, "requested_duration": a.duration, "style": style, "exclude": a.exclude,
           "lyrics": lyrics, "clip_ids": ids, "take_id": cid, "final_clip_id": final_id,
           "take_seconds": dur, "final_seconds": fdur, "extended": final_id != cid,
           "suno_url": "https://suno.com/song/%s" % final_id,
           "files": {"mp3": final, "take_mp3": first}, "credits": {"before": c0, "after": c1}}
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
    print(json.dumps({k: man[k] for k in ("title", "final_clip_id", "final_seconds", "suno_url", "credits")}, indent=1))


if __name__ == "__main__":
    main()
