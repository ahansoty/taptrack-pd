"""Narration: one ElevenLabs clip per sentence (cached by text), normalized to 48 kHz mono WAV.

    python video/tts.py      -> video/out/tts/*.wav and video/out/narration.json (durations per line)
"""
import hashlib
import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from taptrack import config  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "tts"
FF = shutil.which("ffmpeg")


def say(text: str, voice: str) -> Path:
    key = hashlib.sha1(f"{voice}|{text}".encode()).hexdigest()[:16]
    wav = OUT / f"{key}.wav"
    if wav.exists():
        return wav
    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
    mp3 = OUT / f"{key}.mp3"
    audio = client.text_to_speech.convert(
        voice, text=text, model_id="eleven_multilingual_v2", output_format="mp3_44100_128",
        voice_settings={"stability": 0.55, "similarity_boost": 0.8, "style": 0.15, "use_speaker_boost": True})
    mp3.write_bytes(b"".join(audio))
    # trim leading/trailing silence, 48 kHz mono
    trim = ("silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
            "silenceremove=start_periods=1:start_threshold=-50dB,areverse")
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", str(mp3), "-af", trim, "-ac", "1", "-ar", "48000", str(wav)], check=True)
    mp3.unlink()
    return wav


def seconds(wav: Path) -> float:
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    script = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
    voice = script["voice_id"]
    result = {"full": {}, "short": []}
    for sc in script["scenes"]:
        result["full"][sc["id"]] = [{"text": t, "wav": str(say(t, voice)), "sec": round(seconds(say(t, voice)), 3)} for t in sc["lines"]]
    for part in script["short"]:
        result["short"].append({"from": part["from"], "lines": [
            {"text": t, "wav": str(say(t, voice)), "sec": round(seconds(say(t, voice)), 3)} for t in part["lines"]]})
    (HERE / "out" / "narration.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    total = sum(l["sec"] for v in result["full"].values() for l in v)
    print(f"narration: {total:.1f} s speech across {len(result['full'])} scenes; short: "
          f"{sum(l['sec'] for p in result['short'] for l in p['lines']):.1f} s")
    for sid, lines in result["full"].items():
        print(f"  {sid:<9} {sum(l['sec'] for l in lines):5.1f} s  ({len(lines)} lines)")


if __name__ == "__main__":
    main()
