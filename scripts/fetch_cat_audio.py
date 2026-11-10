"""
Test downloading one ESC-50 cat recording.
"""
import urllib.request
import wave
import os

url = "https://raw.githubusercontent.com/karolpiczak/ESC-50/master/audio/1-34094-A-5.wav"
out_path = "test_cat.wav"

try:
    print(f"Downloading {url}...")
    urllib.request.urlretrieve(url, out_path)
    with wave.open(out_path, "rb") as wf:
        print(f"Downloaded successfully! Channels: {wf.getnchannels()}, Rate: {wf.getframerate()}, Frames: {wf.getnframes()}")
    if os.path.exists(out_path):
        os.remove(out_path)
except Exception as e:
    print(f"Download failed: {e}")
