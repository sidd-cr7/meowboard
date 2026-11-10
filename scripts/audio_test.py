"""
MEOWBOARD dedicated audio test tool (no keyboard hook involved).

Examples
  python scripts/audio_test.py --list
  python scripts/audio_test.py --personality KITTEN --category standard --pitch 1.1 --volume 60
  python scripts/audio_test.py --sweep                       # one sound at each pitch bucket
  python scripts/audio_test.py --overlap 30 --interval 20 --channels 12
  python scripts/audio_test.py --burst 200 --channels 4      # stress: bounded, newest wins
  python scripts/audio_test.py --interactive

Prints actual measurements (active channels, queue depth, dropped events, latency).
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meowboard.config.settings import INTENSITY_CHANNELS, PERSONALITIES  # noqa: E402
from meowboard.core.audio_engine import AudioEngine  # noqa: E402
from meowboard.core.sound_manager import CATEGORIES, SoundManager  # noqa: E402

CHANNEL_TO_MODE = {v: k for k, v in INTENSITY_CHANNELS.items()}  # 4/12/24 -> mode


def build(channels: int = 12, volume: int = 80, personality: str = PERSONALITIES[0], assets_dir=None):
    mode = CHANNEL_TO_MODE[channels]
    mgr = SoundManager(assets_dir=assets_dir)
    engine = AudioEngine(sound_manager=mgr, intensity=mode, volume=volume, enabled=True)
    mgr.set_personality(personality)
    return mgr, engine


def play_one(mgr, engine, personality, category, pitch, volume_pct):
    snd = mgr.get_sound(personality, category, pitch)
    if snd is None:
        print(f"  no sound for {personality}/{category}")
        return False
    engine.trigger_sound(snd, volume=volume_pct / 100.0)
    return True


def overlap_test(mgr, engine, personality, category, pitch, volume_pct, count, interval_ms):
    """Fires `count` sounds `interval_ms` apart; returns peak active channels."""
    peak = 0
    t0 = time.perf_counter()
    for i in range(count):
        play_one(mgr, engine, personality, category, pitch, volume_pct)
        peak = max(peak, engine.active_channels)
        time.sleep(interval_ms / 1000.0)
    time.sleep(0.15)
    peak = max(peak, engine.active_channels)
    return {
        "fired": count,
        "peak_active_channels": peak,
        "pending": engine.pending_events,
        "dropped": engine.dropped_events,
        "elapsed_s": round(time.perf_counter() - t0, 3),
    }


def burst_test(mgr, engine, count):
    """Floods the engine as fast as possible; verifies queue bound and no lingering backlog."""
    max_pending = 0
    t0 = time.perf_counter()
    for i in range(count):
        engine.trigger_key(0x41 + (i % 26))
        max_pending = max(max_pending, engine.pending_events)
    submit_s = time.perf_counter() - t0
    time.sleep(0.5)
    return {
        "fired": count,
        "submit_time_ms": round(submit_s * 1000, 2),
        "max_pending": max_pending,
        "pending_after_500ms": engine.pending_events,
        "dropped": engine.dropped_events,
        "active_after": engine.active_channels,
    }


def interactive(mgr, engine):
    st = {"personality": PERSONALITIES[0], "category": "standard", "pitch": 1.0, "volume": 80}
    help_txt = ("commands: p <personality idx 0-3> | c <category> | pitch <0.8-1.3> | vol <0-100> | "
                "ch <4|12|24> | play | rapid <n> | stop | status | q")
    print(help_txt)
    print("personalities:", dict(enumerate(PERSONALITIES)), "categories:", CATEGORIES)
    while True:
        try:
            line = input("> ").strip().split()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        cmd, args = line[0], line[1:]
        try:
            if cmd == "q":
                break
            elif cmd == "p":
                st["personality"] = PERSONALITIES[int(args[0])]
                mgr.set_personality(st["personality"])
            elif cmd == "c":
                st["category"] = args[0]
            elif cmd == "pitch":
                st["pitch"] = float(args[0])
            elif cmd == "vol":
                st["volume"] = int(args[0])
            elif cmd == "ch":
                engine.set_intensity(CHANNEL_TO_MODE[int(args[0])])
            elif cmd == "play":
                play_one(mgr, engine, st["personality"], st["category"], st["pitch"], st["volume"])
            elif cmd == "rapid":
                print(overlap_test(mgr, engine, st["personality"], st["category"], st["pitch"],
                                   st["volume"], int(args[0]) if args else 20, 25))
            elif cmd == "stop":
                engine.stop_all()
            elif cmd == "status":
                print(st, engine.status_message, "pending", engine.pending_events, "dropped", engine.dropped_events)
            else:
                print(help_txt)
        except Exception as e:
            print("error:", e)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list loaded personalities/categories/variants")
    ap.add_argument("--personality", default=PERSONALITIES[0], choices=PERSONALITIES)
    ap.add_argument("--category", default="standard", choices=CATEGORIES)
    ap.add_argument("--pitch", type=float, default=1.0)
    ap.add_argument("--volume", type=int, default=80, help="0-100")
    ap.add_argument("--channels", type=int, default=12, choices=sorted(CHANNEL_TO_MODE))
    ap.add_argument("--sweep", action="store_true", help="play one sound per pitch bucket")
    ap.add_argument("--overlap", type=int, default=0, help="fire N overlapping sounds")
    ap.add_argument("--interval", type=int, default=30, help="ms between overlapping sounds")
    ap.add_argument("--burst", type=int, default=0, help="flood N events as fast as possible")
    ap.add_argument("--all", action="store_true", help="play every personality x category once")
    ap.add_argument("--interactive", action="store_true")
    args = ap.parse_args(argv)

    mgr, engine = build(args.channels, args.volume, args.personality)
    try:
        if args.list:
            for p in PERSONALITIES:
                mgr.preload_personality(p)
                cats = mgr._sound_cache.get(p, {})
                print(p, {c: sum(len(v) for v in b.values()) for c, b in cats.items()})
            print("missing assets:", mgr.missing_assets or "none")
        if args.all:
            for p in PERSONALITIES:
                for c in CATEGORIES:
                    print(f"{p} / {c}")
                    play_one(mgr, engine, p, c, 1.0, args.volume)
                    time.sleep(0.9)
        if args.sweep:
            for pitch in (0.88, 0.92, 0.96, 1.0, 1.04, 1.08, 1.12, 1.16, 1.20):
                print(f"pitch {pitch}")
                play_one(mgr, engine, args.personality, args.category, pitch, args.volume)
                time.sleep(0.8)
        if args.overlap:
            print(overlap_test(mgr, engine, args.personality, args.category, args.pitch,
                               args.volume, args.overlap, args.interval))
        if args.burst:
            print(burst_test(mgr, engine, args.burst))
        if args.interactive:
            interactive(mgr, engine)
        if not any([args.list, args.all, args.sweep, args.overlap, args.burst, args.interactive]):
            play_one(mgr, engine, args.personality, args.category, args.pitch, args.volume)
            time.sleep(1.5)
        time.sleep(0.3)
    finally:
        engine.stop_all()
        engine.shutdown()


if __name__ == "__main__":
    main()
