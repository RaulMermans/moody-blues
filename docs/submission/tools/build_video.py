"""Builds the demo video from real captures. Local only: it uploads nothing.

    python3 docs/submission/tools/build_video.py <shots-dir> <deck-dir> <out-dir>
"""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from narration import SCENES, SPOKEN

VOICE, RATE, FPS = "Samantha", "178", 30
GAP, LEAD, TAIL, MOVE = 0.28, 0.5, 0.7, 1.3
shots, deck, out = (Path(p).resolve() for p in sys.argv[1:4])
work = out / "work"
work.mkdir(parents=True, exist_ok=True)
anchors = json.loads((shots / "anchors.json").read_text())


def run(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True)


def duration(path: Path) -> float:
    probe = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
    return float(subprocess.check_output(probe))


def spoken(line: str) -> str:
    for written, said in SPOKEN.items():
        line = line.replace(written, said)
    return line


def stamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def captions(lines: list[str]) -> None:
    script = Path(__file__).parent / "render_captions.mjs"
    payload = work / "captions.json"
    payload.write_text(json.dumps(lines))
    subprocess.run(["node", str(script), str(payload), str(work)], check=True)


def pan_expr(keys: list[tuple[float, int]]) -> str:
    """Holds at each offset, easing to the next over MOVE seconds."""
    expr = str(keys[-1][1])
    for (start, y0), (end, y1) in reversed(list(zip(keys, keys[1:]))):
        begin = max(start, end - MOVE)
        p = f"((t-{begin:.3f})/{end - begin:.3f})"
        ease = f"({y0}+({y1 - y0})*{p}*{p}*(3-2*{p}))"
        expr = f"if(lt(t,{begin:.3f}),{y0},if(lt(t,{end:.3f}),{ease},{expr}))"
    return expr


all_lines = [line for scene in SCENES for line in scene["lines"]]
captions(all_lines)

index = 0
clock = 0.0
srt: list[str] = []
parts: list[Path] = []
for scene in SCENES:
    sid = scene["id"]
    audio_inputs: list[str] = []
    starts: list[float] = []
    lengths: list[float] = []
    cursor = LEAD
    for n, line in enumerate(scene["lines"]):
        clip = work / f"{sid}-{n}.aiff"
        run("say", "-v", VOICE, "-r", RATE, "-o", str(clip), spoken(line))
        length = duration(clip)
        starts.append(cursor)
        lengths.append(length)
        audio_inputs.append(str(clip))
        cursor += length + GAP
    total = cursor - GAP + TAIL

    delays = ";".join(
        f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={round(s * 1000)}:all=1[a{i}]"
        for i, s in enumerate(starts)
    )
    mix = "".join(f"[a{i}]" for i in range(len(starts)))
    audio = work / f"{sid}.wav"
    args = ["ffmpeg", "-y"]
    for clip_path in audio_inputs:
        args += ["-i", clip_path]
    args += ["-filter_complex", f"{delays};{mix}amix=inputs={len(starts)}:normalize=0,apad=whole_dur={total:.3f}[o]",
             "-map", "[o]", "-t", f"{total:.3f}", str(audio)]
    run(*args)

    if "card" in scene:
        source = deck / f"slide-{scene['card']}.png"
        base = "[0:v]scale=1920:1080,setsar=1[bg]"
    else:
        source = shots / f"{scene['shot']}.png"
        marks = anchors[scene["shot"]]
        limit = int(subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=height", "-of", "csv=p=0", str(source)]
        )) - 1080
        keys: list[tuple[float, int]] = []
        for at, target in sorted(scene["pan"].items()):
            y = target if isinstance(target, int) else max(0, marks[target] - 90)
            keys.append((starts[at], min(y, limit)))
        if keys[0][0] > 0:
            keys[0] = (0.0, keys[0][1])
        base = f"[0:v]crop=1920:1080:0:'{pan_expr(keys)}',setsar=1[bg]"

    inputs = ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.3f}", "-i", str(source)]
    graph = [base]
    last = "bg"
    for n in range(len(scene["lines"])):
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.3f}", "-i", str(work / f"cap-{index + n}.png")]
        end = starts[n] + lengths[n] + GAP * 0.8
        graph.append(f"[{last}][{n + 1}:v]overlay=0:H-h:enable='between(t,{starts[n]:.3f},{end:.3f})'[v{n}]")
        last = f"v{n}"
    graph.append(f"[{last}]fade=t=in:st=0:d=0.3,fade=t=out:st={total - 0.3:.3f}:d=0.3,format=yuv420p[v]")
    inputs += ["-i", str(audio)]
    part = work / f"part-{sid}.mp4"
    run("ffmpeg", "-y", *inputs, "-filter_complex", ";".join(graph), "-map", "[v]",
        "-map", f"{len(scene['lines']) + 1}:a", "-t", f"{total:.3f}", "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(part))
    parts.append(part)

    for n, line in enumerate(scene["lines"]):
        cue = index + n + 1
        srt.append(f"{cue}\n{stamp(clock + starts[n])} --> {stamp(clock + starts[n] + lengths[n])}\n{line}\n")
    index += len(scene["lines"])
    clock += duration(part)
    print(f"{sid}: {total:.1f}s", flush=True)

listing = work / "parts.txt"
listing.write_text("".join(f"file '{p}'\n" for p in parts))
final = out / "moody-blues-demo.mp4"
run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(final))
(out / "moody-blues-demo.srt").write_text("\n".join(srt))
print(f"{final}: {duration(final):.1f}s, {final.stat().st_size / 1e6:.1f} MB")
