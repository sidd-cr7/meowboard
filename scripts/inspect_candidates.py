"""
Script to download, inspect, trim, and categorize real cat recordings.
"""
from pathlib import Path
import urllib.request
import wave
import numpy as np

# Selected high-quality cat recordings from ESC-50 (source: Freesound under CC-BY / CC0)
CANDIDATES = [
    # Normal Cat vocalizations
    {"id": "1-34094-A-5.wav", "src_id": "34094", "author": "NoiseCollector", "license": "CC-BY 3.0", "notes": "Clear domestic cat meow"},
    {"id": "1-34094-B-5.wav", "src_id": "34094", "author": "NoiseCollector", "license": "CC-BY 3.0", "notes": "Second clean meow take"},
    {"id": "1-56380-A-5.wav", "src_id": "56380", "author": "soundbytez", "license": "CC0 (Public Domain)", "notes": "Medium pitch clear meow"},
    {"id": "1-56380-B-5.wav", "src_id": "56380", "author": "soundbytez", "license": "CC0 (Public Domain)", "notes": "Short upbeat meow"},
    {"id": "1-79113-A-5.wav", "src_id": "79113", "author": "dobroide", "license": "CC-BY 3.0", "notes": "Warm inquisitive meow"},
    {"id": "2-82274-A-5.wav", "src_id": "82274", "author": "acclivity", "license": "CC-BY 3.0", "notes": "Resonant vocal cat meow"},
    {"id": "2-83934-A-5.wav", "src_id": "83934", "author": "reinsamba", "license": "CC-BY 3.0", "notes": "Rich domestic meow"},
    # Kitten / High-pitched vocalizations
    {"id": "1-47819-A-5.wav", "src_id": "47819", "author": "sashas", "license": "CC-BY 3.0", "notes": "High pitched kitten meow"},
    {"id": "1-47819-B-5.wav", "src_id": "47819", "author": "sashas", "license": "CC-BY 3.0", "notes": "Short soft kitten cry"},
    {"id": "1-47819-C-5.wav", "src_id": "47819", "author": "sashas", "license": "CC-BY 3.0", "notes": "Gentle kitten chirp"},
    {"id": "3-146964-A-5.wav", "src_id": "146964", "author": "alvin.low", "license": "CC-BY 3.0", "notes": "High inquisitive meow"},
    {"id": "3-146965-A-5.wav", "src_id": "146965", "author": "alvin.low", "license": "CC-BY 3.0", "notes": "Light cheerful vocalization"},
    # Angry / Grumpy / Raspy Cat vocalizations
    {"id": "3-95694-A-5.wav", "src_id": "95694", "author": "temawas", "license": "CC-BY 3.0", "notes": "Angry/growly disgruntled cat meow"},
    {"id": "2-69131-A-5.wav", "src_id": "69131", "author": "juskiddink", "license": "CC-BY 3.0", "notes": "Agitated irritated cat meow"},
    {"id": "2-69131-B-5.wav", "src_id": "69131", "author": "juskiddink", "license": "CC-BY 3.0", "notes": "Sharp complaint meow"},
    # Deep / Resonant Cat vocalizations
    {"id": "4-164064-A-5.wav", "src_id": "164064", "author": "lollosound", "license": "CC-BY 3.0", "notes": "Deep adult male cat meow"},
    {"id": "4-164064-B-5.wav", "src_id": "164064", "author": "lollosound", "license": "CC-BY 3.0", "notes": "Low resonant chest meow"},
    {"id": "5-177957-A-5.wav", "src_id": "177957", "author": "keweldog", "license": "CC0 (Public Domain)", "notes": "Low tone adult cat meow"},
]

print(f"Total candidate audio files to inspect: {len(CANDIDATES)}")
