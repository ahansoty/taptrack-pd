"""Build the TapTrack PD demo video (one command).

    python video/build.py            # full video (~3.5 min) + 60 s cut; reuses cached narration and recordings
    python video/build.py --short    # only re-render the 60 s cut

Inputs
  video/script.json          narration text per scene (accuracy-checked against the system)
  video/out/narration.json   produced by video/tts.py (ElevenLabs, cached per sentence)
  video/out/rec/*.webm|json  real dashboard footage from video/record.py (live, pattern, caregiver, agent, feed)
  video/scenes/scenes.html   animated scenes (hook, watch, split, phone, chat, stack, close)
  audio/src/*.wav            the wrist's real ElevenLabs prompts and beeps (8 kHz)
Footage slots (optional; swapped in automatically when present)
  video/footage/wrist_a.mp4  real wrist footage shown in the wearable scene (16:9 box, right side)
  video/footage/wrist_b.mp4  real wrist footage replacing the animated watch next to the live dashboard
Outputs
  demo_video.mp4, demo_short.mp4, video_script.md (project root)
"""
from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "out"
CLIPS = OUT / "clips"
REC = OUT / "rec"
FOOT = HERE / "footage"
SRC_AUDIO = ROOT / "audio" / "src"
FF = shutil.which("ffmpeg")
FPS = 30
XF = 0.4  # crossfade between scenes
BG = "0xF7F8FA"
FONT_BOLD = "C\\:/Windows/Fonts/segoeuib.ttf"

ACCENT_LED = "#2DB3A6"
BLUE_LED = "#3A6EB5"
PROGRESS_LED = "#DCE6F2"
GREEN_LED = "#3FB37A"


def ff(*args, quiet=True):
    cmd = [FF, "-y"] + (["-loglevel", "error"] if quiet else []) + [str(a) for a in args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + " ".join(cmd[:12]) + "...\n" + r.stderr[-2500:])


def probe(path) -> float:
    r = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def wav_sec(path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def enc(path):
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an", str(path)]


# ---------------------------------------------------------------------------------------------- HTML scenes
def render_html(el: str, data: dict, dur: float, out: Path):
    """Record one animated scene in Chromium at 1920x1080 and trim to exactly `dur` seconds."""
    if out.exists() and out.with_suffix(".json").exists() and json.loads(out.with_suffix(".json").read_text()) == {"el": el, "data": data, "dur": dur}:
        return out
    from playwright.sync_api import sync_playwright

    tmp = OUT / "_html"
    tmp.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(tmp),
                            record_video_size={"width": 1920, "height": 1080})
        t_page = time.time()
        pg = ctx.new_page()
        pg.goto((HERE / "scenes" / "scenes.html").as_uri())
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(900)
        pg.evaluate(f"window.SCENE = {json.dumps({'el': el, **data})}")
        t_start = time.time()
        pg.evaluate("window.start()")
        pg.wait_for_timeout(int(dur * 1000) + 400)
        video = pg.video.path()
        ctx.close()
        b.close()
    ff("-ss", f"{t_start - t_page:.3f}", "-i", video, "-t", f"{dur:.3f}", "-vf", f"fps={FPS},scale=1920:1080", *enc(out))
    Path(video).unlink(missing_ok=True)
    out.with_suffix(".json").write_text(json.dumps({"el": el, "data": data, "dur": dur}))
    return out


def clip_from(src: Path, start: float, end: float, out: Path, speed: float = 1.0, label: str | None = None):
    vf = f"trim=start={start}:end={end},setpts=(PTS-STARTPTS)/{speed},fps={FPS},scale=1920:1080"
    if label:
        vf += (f",drawbox=x=1500:y=24:w=380:h=50:color=0x132238@0.82:t=fill,"
               f"drawtext=fontfile='{FONT_BOLD}':text='{label}':x=1520:y=36:fontsize=26:fontcolor=white")
    ff("-i", src, "-vf", vf, *enc(out))
    return out


def fit(path: Path, dur: float, out: Path):
    """Pad (freeze last frame) or trim a clip to exactly `dur` seconds."""
    have = probe(path)
    pad = max(0.0, dur - have + 0.05)
    ff("-i", path, "-vf", f"tpad=stop_mode=clone:stop_duration={pad:.3f},trim=duration={dur:.3f},setpts=PTS-STARTPTS,fps={FPS}", *enc(out))
    return out


def concat(parts: list[Path], out: Path):
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
    ff("-f", "concat", "-safe", "0", "-i", lst, *enc(out))
    return out


# ---------------------------------------------------------------------------------------------- timeline helpers
class Scene:
    def __init__(self, sid):
        self.id, self.clip, self.dur, self.narr, self.sfx, self.captions = sid, None, 0.0, [], [], True

    def say(self, t, line):
        self.narr.append((t, line["wav"], line["text"], line["sec"]))
        return t + line["sec"]


def lines_of(nar, sid):
    return nar["full"][sid]


def sfx(name):
    return SRC_AUDIO / name


# ---------------------------------------------------------------------------------------------- scenes
def scene_hook(nar):
    s = Scene("hook"); s.captions = False
    l1, l2 = lines_of(nar, "hook")
    words = len(l1["text"].split())
    end1 = s.say(0.7, l1)
    second_at = end1 + 0.35
    end2 = s.say(second_at, l2)
    s.dur = round(end2 + 1.6, 2)
    s.clip = render_html("hook", {"line1": l1["text"], "wordMs": int(l1["sec"] * 1000 / words), "secondAt": second_at}, s.dur, CLIPS / "hook.mp4")
    return s


def scene_wearable(nar):
    s = Scene("wearable")
    L = lines_of(nar, "wearable")
    ev = []
    E = lambda t, **k: ev.append({"t": round(t, 2), **k})
    flip_sec = wav_sec(sfx("flip.wav"))
    E(0.3, type="side", k="The wearable", title="FREE-WILi on the wrist", sub="Screen, five buttons, seven lights, a speaker, a microphone and a motion sensor.")
    E(1.0, type="slot", on=True, name="A", file="wrist_a")
    c = s.say(0.9, L[0]) + 0.5
    # dose
    E(c, type="side", k="Step 1 of 3", title="Log the dose", sub="Red button. Every later check is timed from here.")
    E(c + L[1]["sec"] * 0.35, type="press", c="red")
    E(c + L[1]["sec"] * 0.35 + 0.15, type="screen", n="home_med")
    E(c + L[1]["sec"] * 0.35 + 0.15, type="leds", cols=[BLUE_LED] * 7)
    c = s.say(c, L[1]) + 0.3
    s.sfx.append((c, sfx("dose.wav"), 0))
    E(c + 0.2, type="slot", on=False)
    E(c + 1.4, type="screen", n="home_n")
    E(c + 1.4, type="leds", cols=[])
    c += 1.6
    # start + spoken prompt
    E(c, type="side", k="Step 2 of 3", title="Do the check", sub="Blue starts it. The watch speaks each step.")
    E(c + 1.0, type="press", c="blue")
    E(c + 1.15, type="screen", n="flip")
    c = s.say(c, L[2]) + 0.3
    s.sfx.append((c, sfx("flip.wav"), 0))
    E(c, type="bubble", text="“Flip your hand, palm up, palm down, fast.”")
    E(c + flip_sec, type="bubble", text="")
    c += flip_sec + 0.5
    # four tests (shortened)
    d4 = L[3]["sec"]
    chips = ["Hand flips 10 s", "Tremor 20 s", "Taps 10 s", "Voice 5 s"]
    E(c, type="speed", text="Steps shortened")
    for k, n in enumerate(["flip", "tremor", "taps", "voice"]):
        t = c + k * d4 / 4
        E(t, type="screen", n=n)
        E(t, type="side", k="The four tests", title=["Hand flips", "Hold still", "Alternating taps", "Say “ahhh”"][k],
          sub=["Speed, size and slowing of palm flips.", "Tremor strength and frequency.", "Rhythm and speed on the yellow and green buttons.", "Loudness and steadiness."][k],
          chips=chips, active=k)
        E(t + 0.1, type="progress", dur=d4 / 4 - 0.4, color=PROGRESS_LED, countdown=False)
    c = s.say(c, L[3]) + 0.4
    E(c, type="speed", text="")
    E(c, type="leds", cols=[])
    # LEDs countdown then fill
    E(c, type="side", k="The lights", title="Count down, then fill", sub="Seven LEDs count down before each test and fill while it records.")
    E(c + 0.2, type="screen", n="ready")
    E(c + 1.0, type="press", c="blue")
    E(c + 1.1, type="screen", n="flip")
    E(c + 1.1, type="progress", dur=2.1, color=BLUE_LED, countdown=True)
    for k in range(3):
        s.sfx.append((c + 1.1 + 0.7 * k, sfx("beep.wav"), -6))
    s.sfx.append((c + 3.3, sfx("go.wav"), -6))
    E(c + 3.3, type="progress", dur=max(2.0, L[4]["sec"] - 3.0), color=PROGRESS_LED, countdown=False)
    c = s.say(c, L[4]) + 0.5
    E(c - 0.3, type="leds", cols=[])
    # calculating + result
    E(c, type="side", k="Step 3 of 3", title="Good", sub="The result in words on the screen. The exact score is spoken.")
    E(c + 0.2, type="screen", n="calc")
    E(c + 1.4, type="screen", n="res_g")
    E(c + 1.4, type="leds", cols=[GREEN_LED] * 7)
    E(c + 2.0, type="bubble", text="Spoken aloud: “81”")
    c = s.say(c, L[5]) + 1.3
    s.dur = round(c, 2)
    s.clip = render_html("watchscene", {"events": ev}, s.dur, CLIPS / "wearable_html.mp4")
    foot = FOOT / "wrist_a.mp4"
    if foot.exists():  # real footage into the slot box while it is shown
        on = next(e["t"] for e in ev if e["type"] == "slot" and e.get("on"))
        off = next(e["t"] for e in ev if e["type"] == "slot" and not e.get("on"))
        out = CLIPS / "wearable.mp4"
        ff("-i", s.clip, "-i", foot, "-filter_complex",
           f"[1:v]scale=560:315:force_original_aspect_ratio=increase,crop=560:315,setpts=PTS-STARTPTS+{on}/TB[f];"
           f"[0:v][f]overlay=980:700:enable='between(t,{on},{off})'", *enc(out))
        s.clip = out
    return s


def scene_live(nar):
    s = Scene("live")
    L = lines_of(nar, "live")
    meta = json.loads((REC / "live.json").read_text())
    evs = meta["events"]
    t_start = next(e["t"] for e in evs if e["type"] == "check_started")
    t_res = next(e["t"] for e in evs if e["type"] == "check_result")
    score = next(e["score"] for e in evs if e["type"] == "check_result")
    SPEED = 2.0
    s0, e0 = t_start - 1.0, t_res + 3.5
    A = (e0 - s0) / SPEED
    rel = lambda t: (t - s0) / SPEED
    ev = [{"t": 0.0, "type": "speed", "text": f"Sped up {SPEED:g}x"}]
    steps = [e for e in evs if e["type"] == "step"]
    for i, e in enumerate(steps):
        if e["phase"] == "instruct":
            ev.append({"t": round(rel(e["t"]), 2), "type": "screen", "n": e["step"]})
        if e["phase"] == "record":
            done = next(x["t"] for x in steps[i:] if x["step"] == e["step"] and x["phase"] == "done")
            ev.append({"t": round(rel(e["t"]), 2), "type": "progress", "dur": round((done - e["t"]) / SPEED, 2), "color": PROGRESS_LED, "countdown": False})
    last_done = max(e["t"] for e in steps if e["phase"] == "done")
    ev += [{"t": round(rel(last_done), 2), "type": "screen", "n": "calc"},
           {"t": round(rel(t_res) + 0.4, 2), "type": "screen", "n": "res_g"},
           {"t": round(rel(t_res) + 0.4, 2), "type": "leds", "cols": [GREEN_LED] * 7},
           {"t": round(rel(t_res) + 0.8, 2), "type": "bubble", "text": f"Spoken aloud: “{score}”"}]
    html = render_html("split", {"events": ev}, round(A, 2), CLIPS / "live_html.mp4")
    dash = CLIPS / "live_dash.mp4"
    ff("-i", REC / "live.webm", "-vf", f"trim=start={s0}:end={e0},setpts=(PTS-STARTPTS)/{SPEED},fps={FPS},scale=1136:640", *enc(dash))
    partA = CLIPS / "live_a.mp4"
    graph = "[0:v][1:v]overlay=702:191:shortest=1[v]"
    inputs = ["-i", html, "-i", dash]
    foot = FOOT / "wrist_b.mp4"
    if foot.exists():
        inputs += ["-i", foot]
        graph = ("[0:v][1:v]overlay=702:191:shortest=1[a];[2:v]scale=620:827:force_original_aspect_ratio=increase,crop=620:827[f];"
                 "[a][f]overlay=40:150:shortest=0[v]")
    ff(*inputs, "-filter_complex", graph, "-map", "[v]", "-t", f"{A:.3f}", *enc(partA))
    # narration: first two lines up front, the third ends as the score lands
    c = s.say(0.8, L[0]) + 0.6
    c = s.say(c, L[1]) + 0.6
    s.say(max(c, rel(t_res) - L[2]["sec"] + 1.2), L[2])
    # part B: clinician and caregiver side by side
    B = round(L[3]["sec"] + 2.2, 2)
    still = CLIPS / "live_last.png"
    ff("-sseof", "-0.5", "-i", REC / "live.webm", "-frames:v", "1", still)
    partB = CLIPS / "live_b.mp4"
    ff("-f", "lavfi", "-i", f"color=c={BG}:s=1920x1080:r={FPS}:d={B}", "-loop", "1", "-t", f"{B}", "-i", still,
       "-ss", "1", "-i", REC / "caregiver.webm", "-filter_complex",
       f"[1:v]scale=900:506[l];[2:v]scale=900:506,tpad=stop_mode=clone:stop_duration={B}[r];"
       f"[0:v][l]overlay=50:300[a];[a][r]overlay=970:300:shortest=1,"
       f"drawtext=fontfile='{FONT_BOLD}':text='CLINICIAN':x=50:y=245:fontsize=30:fontcolor=0x5F6B80,"
       f"drawtext=fontfile='{FONT_BOLD}':text='CAREGIVER':x=970:y=245:fontsize=30:fontcolor=0x5F6B80,"
       f"drawbox=x=49:y=299:w=902:h=508:color=0xD5DBE5:t=2,drawbox=x=969:y=299:w=902:h=508:color=0xD5DBE5:t=2[v]",
       "-map", "[v]", "-t", f"{B}", *enc(partB))
    s.say(A + 0.5, L[3])
    s.dur = round(A + B, 2)
    s.clip = concat([partA, partB], CLIPS / "live.mp4")
    return s


def scene_pattern(nar):
    s = Scene("pattern")
    L = lines_of(nar, "pattern")
    c = 0.6
    for l in L:
        c = s.say(c, l) + 0.55
    src = REC / "pattern.webm"
    s.dur = round(max(probe(src) - 0.3, c + 0.8), 2)
    raw = CLIPS / "pattern_raw.mp4"
    ff("-i", src, "-vf", f"fps={FPS},scale=1920:1080,"
       f"drawbox=x=1380:y=24:w=500:h=50:color=0x132238@0.82:t=fill,"
       f"drawtext=fontfile='{FONT_BOLD}':text='SIMULATED PATIENT · 14 DAYS':x=1400:y=36:fontsize=26:fontcolor=white", *enc(raw))
    s.clip = fit(raw, s.dur, CLIPS / "pattern.mp4")
    return s


def scene_agent(nar):
    s = Scene("agent")
    L = lines_of(nar, "agent")
    src = REC / "agent.webm"
    s1 = clip_from(src, 4.0, 8.5, CLIPS / "agent_1.mp4")
    s2 = clip_from(src, 10.0, 64.0, CLIPS / "agent_2.mp4", speed=9.0, label="SPED UP 9X")
    s3 = clip_from(src, 64.5, 69.5, CLIPS / "agent_3.mp4")
    t = s.say(0.6, L[0])
    head = probe(s1) + probe(s2) + probe(s3)
    # phone: the alert, the caregiver's "today", the reply, the report text (texts exactly as produced)
    d2, d3 = L[1]["sec"], L[2]["sec"]
    P = round(d2 + d3 + 2.6, 2)
    alert = ("TapTrack alert: Harriet's 3:16 AM check was much lower than usual (score 32; usual is about 85). "
             "It was 1 h 7 min after the last dose. Reply 'today' for a summary.")
    reply = ("Today: 5 checks, average 60. Latest at 3:16 AM was much lower than usual (32). Lowest was 32 at 3:16 AM, "
             "1 h 7 min after the last dose. 4 doses logged, 0 checks missed.")
    report = ("TapTrack sent Harriet's 14-day visit report to Dr. Patel (Movement Disorders Clinic) and requested a "
              "follow-up visit. Proposed follow-up: Tue Oct 6, 10:30 AM. The report shows scores dropping about 2.5 h after doses.")
    phone = render_html("phone", {"msgs": [{"t": 0.5, "who": "them", "text": alert}, {"t": d2 + 0.7, "who": "me", "text": "today"},
                                           {"t": d2 + 1.9, "who": "them", "text": reply}, {"t": P - 1.4, "who": "them", "text": report}]},
                        P, CLIPS / "agent_phone.mp4")
    s.say(max(t + 0.4, head) + 0.4, L[1])
    s.say(head + d2 + 1.0, L[2])
    F = round(max(6.5, L[3]["sec"] + 1.0), 2)
    feed = fit(clip_from(REC / "feed.webm", 3.5, 11.0, CLIPS / "agent_feed_raw.mp4"), F, CLIPS / "agent_feed.mp4")
    s.say(head + P + 0.4, L[3])
    Cd = round(max(8.0, L[4]["sec"] + 6.0), 2)
    chat = render_html("chatscene", {"q": "How is she doing today?", "answerAt": 1.2,
                                     "a": reply + "\n\n(Decision support only. Not a diagnostic device.)"}, Cd, CLIPS / "agent_chat.mp4")
    s.say(head + P + F + 0.4, L[4])
    s.dur = round(head + P + F + Cd, 2)
    s.clip = concat([s1, s2, s3, phone, feed, chat], CLIPS / "agent.mp4")
    return s


def scene_stack(nar):
    s = Scene("stack")
    (l,) = lines_of(nar, "stack")
    cards = [["FREE-WILi", "The wearable: buttons, motion sensor, mic, screen, lights, speaker."],
             ["ElevenLabs", "The spoken instructions on the wrist."],
             ["TimescaleDB on Neon", "Hypertables for checks, doses and passive tremor."],
             ["FinchNode", "The patient record and medications (synthetic demo patient)."],
             ["Gemini", "The neurologist report and patient summary. Patterns only."],
             ["Fetch.ai", "The care agent and clinic agent, on Agentverse and ASI:One."],
             ["Photon", "iMessage alerts and two-way caregiver chat."],
             ["Figma", "Wrist screens exported as frames for design edits."],
             ["taptrack.tech", "The project site."]]
    s.say(0.6, l)
    s.dur = round(l["sec"] + 2.6, 2)
    s.clip = render_html("stack", {"cards": cards, "stepMs": int(l["sec"] * 1000 / 9)}, s.dur, CLIPS / "stack.mp4")
    return s


def scene_close(nar):
    s = Scene("close"); s.captions = False
    (l,) = lines_of(nar, "close")
    s.say(0.8, l)
    s.dur = round(max(9.0, l["sec"] + 4.0), 2)
    s.clip = render_html("close", {}, s.dur, CLIPS / "close.mp4")
    return s


# ---------------------------------------------------------------------------------------------- audio, captions, assembly
def music_bed(seconds: float, path: Path, rate=48000):
    """Soft generated pad (royalty-free): slow chords of sine partials with gentle swells."""
    chords = [[261.63, 329.63, 392.0, 493.88], [220.0, 261.63, 329.63, 392.0], [174.61, 220.0, 261.63, 329.63], [196.0, 246.94, 293.66, 392.0]]
    n = int(seconds * rate)
    seg = 8.0
    frames = bytearray()
    for i in range(n):
        t = i / rate
        k = int(t // seg) % len(chords)
        ph = (t % seg) / seg
        env = math.sin(math.pi * ph) ** 0.8
        v = sum(math.sin(2 * math.pi * f * t) + 0.3 * math.sin(4 * math.pi * f * t) for f in chords[k]) / 6.0
        v *= 0.18 * env * min(1.0, t / 2.0) * min(1.0, (seconds - t) / 3.0)
        s = int(max(-1, min(1, v)) * 32767)
        frames += struct.pack("<hh", s, s)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(frames))


def mix_audio(items, total: float, out: Path, music: Path | None):
    """items: (abs_t, wav, gain_db). Narration at 0 dB, wrist prompts slightly lower, music bed far below."""
    inputs, chains = [], []
    for i, (t, wav, g) in enumerate(items):
        inputs += ["-i", wav]
        ms = max(0, int(t * 1000))
        chains.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,volume={g}dB,adelay={ms}|{ms}[a{i}]")
    k = len(items)
    labels = "".join(f"[a{i}]" for i in range(k))
    if music:
        inputs += ["-i", music]
        chains.append(f"[{k}:a]volume=-21dB[m]")
        labels += "[m]"
        k += 1
    graph = ";".join(chains) + f";{labels}amix=inputs={k}:normalize=0:duration=longest,atrim=0:{total:.3f},loudnorm=I=-16:TP=-1.5:LRA=11[out]"
    script = out.with_suffix(".filter.txt")
    script.write_text(graph)
    ff(*inputs, "-/filter_complex", script, "-map", "[out]", "-ar", "48000", "-c:a", "pcm_s16le", out)


def ass_time(t):
    h, rem = divmod(max(0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def chunks(text, maxlen=62):
    words, out, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > maxlen and cur:
            out.append(cur); cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return out


def write_ass(caps, path: Path):
    head = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Segoe UI Semibold,44,&H00FFFFFF,&H00FFFFFF,&H5A382213,&H5A382213,0,0,0,0,100,100,0,0,3,14,0,2,200,200,46,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for t, dur, text in caps:
        parts = chunks(text)
        total = sum(len(p) for p in parts)
        c = t
        for p in parts:
            d = dur * len(p) / total
            lines.append(f"Dialogue: 0,{ass_time(c)},{ass_time(c + d)},Cap,,0,0,0,,{p}")
            c += d
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def xfade_chain(clips: list[Path], durs: list[float], out: Path):
    inputs = []
    for c in clips:
        inputs += ["-i", c]
    # every clip is held on its last frame / trimmed to its exact planned length (xfade stops at the shortest input)
    graph = [f"[{i}:v]tpad=stop_mode=clone:stop_duration=3,trim=duration={d:.3f},setpts=PTS-STARTPTS,fps={FPS},settb=AVTB[c{i}]"
             for i, d in enumerate(durs)]
    prev, offset = "[c0]", 0.0
    for i in range(1, len(clips)):
        offset += durs[i - 1] - XF
        graph.append(f"{prev}[c{i}]xfade=transition=fade:duration={XF}:offset={offset:.3f}[x{i}]")
        prev = f"[x{i}]"
    ff(*inputs, "-filter_complex", ";".join(graph), "-map", prev, *enc(out))


def assemble(scenes: list[Scene], name: str, script_md: Path | None = None):
    starts, t = [], 0.0
    for sc in scenes:
        starts.append(t)
        t += sc.dur - XF
    total = t + XF
    items, caps = [], []
    for sc, st in zip(scenes, starts):
        for (tt, wav, text, sec) in sc.narr:
            items.append((st + tt, wav, 0))
            if sc.captions:
                caps.append((st + tt, sec, text))
        for (tt, wav, g) in sc.sfx:
            items.append((st + tt, wav, g + 2))
    video = OUT / f"{name}_video.mp4"
    xfade_chain([sc.clip for sc in scenes], [sc.dur for sc in scenes], video)
    music = OUT / f"{name}_music.wav"
    music_bed(total, music)
    audio = OUT / f"{name}_audio.wav"
    mix_audio(items, total, audio, music)
    ass = OUT / f"{name}.ass"
    write_ass(caps, ass)
    final = ROOT / f"{name}.mp4"
    subprocess_cwd_ff(["-i", video, "-i", audio, "-vf", f"subtitles={ass.name}", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
                       "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", final], cwd=OUT)
    if script_md:
        write_script_md(scenes, starts, total, script_md)
    return final, total


def subprocess_cwd_ff(args, cwd):
    r = subprocess.run([FF, "-y", "-loglevel", "error"] + [str(a) for a in args], cwd=str(cwd), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2500:])


def write_script_md(scenes, starts, total, path):
    script = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
    titles = {s["id"]: (s["title"], s["visual"]) for s in script["scenes"]}
    out = ["# TapTrack PD demo video: narration script", "",
           f"Length {int(total // 60)}:{int(total % 60):02d}. Voice: {script['voice_name']}. Rebuild: `python video/build.py`.",
           "All patient data is synthetic. Decision support only; no dose advice.", ""]
    for sc, st in zip(scenes, starts):
        title, visual = titles.get(sc.id, (sc.id, ""))
        out.append(f"## {int(st // 60)}:{int(st % 60):02d} {title}")
        out.append(f"_Visual: {visual}_  ")
        for (tt, _, text, _) in sc.narr:
            out.append(f"- **{int((st + tt) // 60)}:{(st + tt) % 60:04.1f}** {text}")
        out.append("")
    out += ["## Footage slots", "- `video/footage/wrist_a.mp4`: real wrist footage shown in the wearable scene (box on the right).",
            "- `video/footage/wrist_b.mp4`: real wrist footage replacing the animated watch beside the live dashboard.",
            "Drop the files in and run `python video/build.py`."]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------- short cut
SHORT_LEN = {"hook": 7.0, "wearable": 13.5, "live": 11.5, "pattern": 10.5, "agent": 12.5, "close": 7.0}
IRL = ROOT / "video_irl.MOV"          # real filmed check (portrait); replaces the animated watch in the short when present
IRL_IN, IRL_OUT, IRL_SPEED = 2.0, 91.5, 6.0


def irl_segment(dur: float, out: Path):
    """The filmed check, sped up, framed on the left with a label on the right."""
    tf = OUT / "irl_text"
    tf.mkdir(exist_ok=True)
    texts = {"k": "THE REAL WEARABLE", "t": "A one-minute check", "b": "Hand flips · Hold still · Taps · Say “ahhh”",
             "n": f"Filmed on the FREE-WILi · sped up {IRL_SPEED:g}x", "r": "Lights count down, then fill.  Red means much lower."}
    for k, v in texts.items():
        (tf / f"{k}.txt").write_text(v, encoding="utf-8")
    font = FONT_BOLD
    reg = "C\:/Windows/Fonts/segoeui.ttf"
    T = lambda k: (tf / f"{k}.txt").as_posix().replace(":", "\:")
    graph = (f"[1:v]trim=start={IRL_IN}:end={IRL_OUT},setpts=(PTS-STARTPTS)/{IRL_SPEED},fps={FPS},crop=iw:iw*4/3:0:(ih-oh)*0.45,scale=676:900,"
             f"tpad=stop_mode=clone:stop_duration={dur}[v];"
             f"[0:v]drawbox=x=176:y=42:w=692:h=916:color=0x132238:t=fill[bg];"
             f"[bg][v]overlay=184:50:shortest=0,"
             f"drawtext=fontfile='{font}':textfile='{T('k')}':x=960:y=330:fontsize=30:fontcolor=0x2DB3A6,"
             f"drawtext=fontfile='{font}':textfile='{T('t')}':x=956:y=380:fontsize=80:fontcolor=0x132238,"
             f"drawtext=fontfile='{reg}':textfile='{T('b')}':x=960:y=500:fontsize=38:fontcolor=0x3D4A60,"
             f"drawtext=fontfile='{reg}':textfile='{T('r')}':x=960:y=560:fontsize=38:fontcolor=0x3D4A60,"
             f"drawtext=fontfile='{font}':textfile='{T('n')}':x=960:y=650:fontsize=28:fontcolor=0x5F6B80,"
             f"trim=duration={dur},setpts=PTS-STARTPTS[o]")
    ff("-f", "lavfi", "-i", f"color=c={BG}:s=1920x1080:r={FPS}:d={dur}", "-i", IRL, "-filter_complex", graph,
       "-map", "[o]", *enc(out))
    return out


def build_short(nar, full):
    """60 s cut from the rendered scenes with its own short narration."""
    by = {s.id: s for s in full}
    parts, scenes = [], []
    plan = {p["from"]: p["lines"][0] for p in nar["short"]}
    windows = {"hook": (0.0, None), "wearable": (None, None), "live": (None, None), "pattern": (4.0, None), "agent": (None, None), "close": (0.0, None)}
    for sid in ["hook", "wearable", "live", "pattern", "agent", "close"]:
        line = plan[sid]
        # ~60 s total: each segment holds its visual a few seconds past the line
        dur = round(max(line["sec"] + 1.6, SHORT_LEN[sid]), 2)
        if IRL.exists() and sid in ("wearable", "live"):   # the filmed check takes the time; the live clip gets shorter
            dur = {"wearable": round((IRL_OUT - IRL_IN) / IRL_SPEED + 2.0, 2), "live": 8.0}[sid]
        src = by[sid]
        if sid == "wearable":   # the tests cycling on the watch
            start = next(tt for (tt, _, text, _) in src.narr if text.startswith("Ten seconds")) - 0.2
        elif sid == "live":     # the score landing live
            start = max(0, src.narr[2][0] + src.narr[2][3] - dur + 1.0)
        elif sid == "agent":    # the phone
            start = src.narr[1][0] - 0.3
        else:
            start = windows[sid][0]
        clip = OUT / "clips" / f"short_{sid}.mp4"
        if sid == "wearable" and IRL.exists():
            irl_segment(dur, clip)
        else:
            ff("-ss", f"{start:.3f}", "-i", src.clip, "-t", f"{dur:.3f}", *enc(clip))
        sc = Scene(sid)
        sc.clip, sc.dur, sc.captions = clip, dur, sid not in ("hook", "close")
        sc.narr = [(0.5 if sid != "close" else 0.8, line["wav"], line["text"], line["sec"])]
        scenes.append(sc)
    return assemble(scenes, "demo_short")


def main():
    CLIPS.mkdir(parents=True, exist_ok=True)
    nar_path = OUT / "narration.json"
    if not nar_path.exists():
        subprocess.run([sys.executable, str(HERE / "tts.py")], check=True)
    nar = json.loads(nar_path.read_text(encoding="utf-8"))
    t0 = time.time()
    builders = [scene_hook, scene_wearable, scene_live, scene_pattern, scene_agent, scene_stack, scene_close]
    scenes = []
    for b in builders:
        sc = b(nar)
        print(f"  scene {sc.id:<9} {sc.dur:6.1f} s   ({time.time() - t0:.0f} s elapsed)", flush=True)
        scenes.append(sc)
    if "--short" not in sys.argv:
        final, total = assemble(scenes, "demo_video", ROOT / "video_script.md")
        print(f"full: {final}  {total:.1f} s")
    short, st = build_short(nar, scenes)
    print(f"short: {short}  {st:.1f} s  (total build {time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
