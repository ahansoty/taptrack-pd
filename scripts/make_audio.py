"""Generate the spoken test instructions and upload them to the FREE-WILi.

    python scripts/make_audio.py              # generate audio/out/*.wav (mono, 16-bit, FW_WAV_RATE Hz)
    python scripts/make_audio.py --upload     # ...and upload to /sounds on the device (8.3 names)
    python scripts/make_audio.py --upload --play flip.wav

Voice: ElevenLabs when ELEVENLABS_API_KEY is set (PCM straight from the API, no resampling),
otherwise the Windows SAPI voice (resampled with ffmpeg) so the wrist still speaks.
The bridge plays these from the device during a check and falls back to laptop audio if a
file is missing or playback fails. FW_WAV_RATE defaults to 16000 (8000/16000/22050 all played
in the hardware test; lower = faster upload, ~25 KB/s).
"""
import argparse
import io
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from taptrack import audio, config  # noqa: E402

EL_RATES = (8000, 16000, 22050, 24000, 44100)


def write_wav(path: Path, pcm: bytes, rate: int):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def elevenlabs_wav(text: str, path: Path, rate: int):
    from elevenlabs.client import ElevenLabs

    if rate not in EL_RATES:
        raise ValueError(f"ElevenLabs PCM rates: {EL_RATES}")
    client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
    chunks = client.text_to_speech.convert(
        config.ELEVENLABS_VOICE_ID, text=text, model_id=config.env("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
        output_format=f"pcm_{rate}")
    write_wav(path, b"".join(chunks), rate)


def sapi_wav(text: str, path: Path, rate: int):
    """Windows built-in voice -> wav, then ffmpeg to mono 16-bit at `rate`."""
    tmp = Path(tempfile.mkdtemp()) / "sapi.wav"
    safe = text.replace("'", "''")
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.Rate = -1; $s.SetOutputToWaveFile('{tmp}'); $s.Speak('{safe}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True, timeout=60)
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg not found for resampling")
    trim = ("silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
            "silenceremove=start_periods=1:start_threshold=-45dB,areverse,apad=pad_dur=0.15")
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(tmp), "-af", trim, "-ac", "1", "-ar", str(rate),
                    "-sample_fmt", "s16", str(path)], check=True)


def generate(rate: int) -> list[Path]:
    audio.SRC_DIR.mkdir(parents=True, exist_ok=True)
    engine = "elevenlabs" if config.ELEVENLABS_API_KEY else "windows-sapi"
    out = []
    for name, text in audio.PROMPTS.items():
        path = audio.SRC_DIR / name
        used = engine
        try:
            (elevenlabs_wav if engine == "elevenlabs" else sapi_wav)(text, path, rate)
        except Exception as ex:
            msg = str(getattr(ex, "body", "") or ex)[:160]
            print(f"  {name}: {engine} failed ({msg})" + ("; using windows-sapi" if engine == "elevenlabs" else ""))
            if engine != "elevenlabs":
                raise
            sapi_wav(text, path, rate)
            used = "windows-sapi"
        with wave.open(str(path)) as w:
            secs = w.getnframes() / w.getframerate()
            assert w.getnchannels() == 1 and w.getsampwidth() == 2, "must be mono 16-bit"
        print(f"  {name:<12} {secs:4.1f} s  {path.stat().st_size // 1024} KB  ({used}, {rate} Hz)")
        out.append(path)
    audio.ensure_beeps()
    audio.apply_volume()
    print(f"scaled to volume {config.VOLUME:.2f} -> {audio.OUT_DIR}")
    return out


def upload(play: str | None):
    from taptrack.bridge import Bridge
    from taptrack.device import FreeWiliDevice
    from taptrack.storage import get_store

    dev = FreeWiliDevice()
    if not dev.open():
        sys.exit("No FREE-WILi found")
    b = Bridge(get_store(), device=dev)
    b.device = dev
    b._sync_sounds()  # uploads anything new or changed (size-stamped), 8.3 names into /sounds
    print("sounds on device:", sorted(dev.sounds))
    if play:
        print("play", play, dev.play(play) if not config.QUIET else "(QUIET=true, skipped)")
    dev.dev.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=int, default=config.FW_WAV_RATE)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--play")
    ap.add_argument("--volume-only", action="store_true", help="re-scale existing recordings, no new TTS")
    a = ap.parse_args()
    if a.volume_only:
        audio.ensure_beeps()
        print("scaled:", [p.name for p in audio.apply_volume()], f"at {config.VOLUME:.2f}")
    else:
        print("generating:")
        generate(a.rate)
    if a.upload:
        upload(a.play)
