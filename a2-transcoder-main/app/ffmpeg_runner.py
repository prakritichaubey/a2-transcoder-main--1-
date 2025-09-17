# app/ffmpeg_runner.py
from __future__ import annotations
import subprocess, time, os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any

def _args_for_intensity(level: str) -> list[str]:
    level = (level or "high").lower()
    if level == "low":
        return ["-c:v", "libx264", "-preset", "faster",  "-threads", "0"]
    if level == "medium":
        return ["-c:v", "libx264", "-preset", "slow",    "-threads", "0"]
    if level == "max":
        # Extremely heavy – only use for short demos
        return [
            "-c:v", "libx264", "-preset", "placebo", "-tune", "film", "-threads", "0",
            "-x264-params", "me=tesa:subme=10:merange=64:ref=6:rc-lookahead=60"
        ]
    # default: "high"
    return ["-c:v", "libx264", "-preset", "veryslow", "-threads", "0"]


def _one(
    in_path: Path,
    out_path: Path,
    width: int,
    height: int,
    crf: int,
    intensity: str,
) -> dict:
    """
    Run a single ffmpeg transcode and return result dict.
    """
    scale = f"scale={width}:{height}:flags=lanczos"
    extra = _args_for_intensity(intensity)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(in_path),
        "-vf", scale,
        *extra,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",  # drop audio to keep CPU on video; remove to encode audio too
        str(out_path),
    ]

    t0 = time.time()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    dt = round(time.time() - t0, 2)

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffmpeg failed")

    return {"path": str(out_path), "cmd": " ".join(cmd), "seconds": dt}


def transcode(in_path: Path, out_dir: Path, specs: List[Dict[str, Any]], intensity: str = "high",) -> List[dict]:
    """
    specs: list like [{"width":1920,"height":1080,"crf":24,"suffix":"1080p"}, ...]
    Returns: list of {"path": str, "cmd": str, "seconds": float}
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results: List[dict] = []
    futures = []

    max_workers = min(8, os.cpu_count() or 2)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for r in specs:
            w = int(r.get("width", 1280))
            h = int(r.get("height", 720))
            crf = int(r.get("crf", 23))
            suffix = r.get("suffix", f"{w}x{h}")
            out_path = out_dir / f"{in_path.stem}_{suffix}.mp4"

            futures.append(ex.submit(_one, in_path, out_path, w, h, crf, intensity))

        for fut in as_completed(futures):
            results.append(fut.result())

    return results