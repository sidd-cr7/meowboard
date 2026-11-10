"""
Inspects pitch, duration, and spectral features of the downloaded real cat recordings.
"""
from pathlib import Path
import wave
import numpy as np

SOURCE_DIR = Path(__file__).resolve().parent.parent / "meowboard" / "assets" / "source_recordings"

def estimate_pitch(audio: np.ndarray, sr: int) -> float:
    """Estimates dominant fundamental frequency via autocorrelation."""
    # Work on a center slice with high energy
    win_len = int(sr * 0.1)
    if len(audio) < win_len:
        return 0.0
    center = len(audio) // 2
    slice_audio = audio[center - win_len // 2 : center + win_len // 2]

    # Autocorrelation
    corr = np.correlate(slice_audio, slice_audio, mode='full')
    corr = corr[len(corr)//2:]

    # Search in feline vocal range: 150 Hz to 1500 Hz
    min_lag = int(sr / 1500)
    max_lag = int(sr / 150)

    if max_lag >= len(corr):
        max_lag = len(corr) - 1

    peak_lag = min_lag + np.argmax(corr[min_lag:max_lag])
    f0 = sr / peak_lag if peak_lag > 0 else 0.0
    return round(float(f0), 1)

print("=" * 60)
print(f"{'Filename':<18} | {'Duration':<8} | {'Est. f0 (Hz)':<12} | {'Energy RMS'}")
print("-" * 60)

for p in sorted(SOURCE_DIR.glob("*.wav")):
    with wave.open(str(p), "rb") as wf:
        sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        raw = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        dur = len(raw) / sr
        f0 = estimate_pitch(raw, sr)
        rms = np.sqrt(np.mean(raw ** 2))
        print(f"{p.name:<18} | {dur:<8.2f} | {f0:<12.1f} | {rms:<.4f}")
