"""
High-Performance, Low-Latency Audio Engine for MEOWBOARD.
Implements bounded channel pooling, oldest-channel stealing, zero backlog,
anti-clipping scaling, and graceful audio-device recovery.
"""
from collections import deque
import queue
import random
import threading
import time
from typing import Callable, List, Optional, Tuple

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    pygame = None
    PYGAME_AVAILABLE = False

from ..config.settings import (
    DEFAULT_AUDIO_BUFFER,
    DEFAULT_AUDIO_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    INTENSITY_CHANNELS,
    PERSONALITY_NORMAL,
)
from ..utils.logger import logger
from .pitch_mapper import KeyProfile
from .sound_manager import SoundManager


QUEUE_MAX = 32            # hard bound on pending triggers
MAX_EVENT_AGE_S = 0.12    # events older than this are dropped rather than played late


class AudioEngine:
    """
    Event-driven audio engine designed for zero playback latency and strict bounded resources.
    Never accumulates an audio backlog. Steals the oldest playing channel when saturated.
    """

    def __init__(
        self,
        sound_manager: Optional[SoundManager] = None,
        intensity: str = "NORMAL",
        volume: int = 75,
        enabled: bool = True,
        on_key_played: Optional[Callable[[KeyProfile], None]] = None,
    ):
        self._sound_manager = sound_manager
        self._intensity = intensity if intensity in INTENSITY_CHANNELS else "NORMAL"
        self._volume = max(0, min(100, volume))
        self._enabled = enabled
        self._on_key_played = on_key_played

        self._lock = threading.Lock()
        self._is_running = True
        self._device_healthy = False
        self._last_error = ""

        # Non-blocking trigger queue strictly bounded to 32 items to guarantee NO backlog
        self._queue: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._dropped_stale = 0
        self._dropped_full = 0
        self._last_recovery = 0.0
        self._last_active = 0
        self._restart_thread = None

        # Active channel pool tracking
        self._channels: List = []
        self._channel_timestamps: List[float] = []

        # Background worker thread
        self._worker_thread: Optional[threading.Thread] = None

        # Initialize audio backend
        self._init_backend()
        self._start_worker()

    def _init_backend(self, mark_healthy: bool = True) -> bool:
        """Initializes pygame.mixer with low-latency buffer settings."""
        if not PYGAME_AVAILABLE:
            self._last_error = "Pygame is not installed"
            logger.error(self._last_error)
            self._device_healthy = False
            return False

        try:
            if pygame.mixer.get_init():
                pygame.mixer.quit()

            pygame.mixer.pre_init(
                frequency=DEFAULT_SAMPLE_RATE,
                size=-16,
                channels=DEFAULT_AUDIO_CHANNELS,
                buffer=DEFAULT_AUDIO_BUFFER,
            )
            pygame.mixer.init()

            # Allocate maximum possible channels (Chaos mode = 24)
            max_alloc = max(INTENSITY_CHANNELS.values())
            pygame.mixer.set_num_channels(max_alloc)

            self._channels = [pygame.mixer.Channel(i) for i in range(max_alloc)]
            self._channel_timestamps = [0.0] * max_alloc
            self._device_healthy = mark_healthy
            self._last_error = ""
            if self._sound_manager is not None:
                self._sound_manager.finalize_sounds()
            logger.info("AudioEngine initialized successfully (sample_rate=%d, buffer=%d, channels=%d)",
                        DEFAULT_SAMPLE_RATE, DEFAULT_AUDIO_BUFFER, max_alloc)
            return True
        except Exception as e:
            self._device_healthy = False
            self._last_error = f"Audio init failed: {e}"
            logger.error(self._last_error)
            return False

    def _start_worker(self):
        """Starts dedicated audio dispatch thread to decouple from input detection."""
        self._worker_thread = threading.Thread(
            target=self._audio_loop,
            name="MeowAudioWorker",
            daemon=True,
        )
        self._worker_thread.start()

    def _audio_loop(self):
        """Drains trigger queue and routes to channel pool."""
        while self._is_running:
            try:
                # Wait for next key trigger with a short timeout
                ts, vk_code, sound, volume = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue

            try:
                if not self._enabled or not self._device_healthy or self._sound_manager is None:
                    continue
                # Never play late: a stale event is dropped, not delayed (no accumulating lag)
                if time.perf_counter() - ts > MAX_EVENT_AGE_S:
                    self._dropped_stale += 1
                    continue
                self._play_key_sound(vk_code, sound, volume)
            except Exception as e:  # the worker must never die
                logger.warning("Audio worker error: %s", e)
            finally:
                self._queue.task_done()

    def _calculate_channel_volume(self) -> float:
        """
        Anti-clipping dynamic volume scaling based on intensity channel limits.
        """
        base_vol = (self._volume / 100.0)
        # Scaled headroom according to maximum simultaneous channels
        if self._intensity == "CHILL":
            headroom = 0.85
        elif self._intensity == "NORMAL":
            headroom = 0.58
        else:  # CHAOS
            headroom = 0.40
        return max(0.0, min(1.0, base_vol * headroom))

    def _play_key_sound(self, vk_code: int, sound=None, volume=None):
        """Plays on an idle channel, else steals the OLDEST channel so the NEWEST event always sounds."""
        try:
            if sound is not None:
                sound_obj = sound
                profile = self._sound_manager._pitch_mapper.get_key_profile(vk_code)
            else:
                sound_obj, profile = self._sound_manager.get_sound_for_key(vk_code)
            if sound_obj is None or not hasattr(sound_obj, "play"):
                return

            limit = INTENSITY_CHANNELS.get(self._intensity, 12)
            now = time.perf_counter()

            target_channel = None
            target_idx = -1

            with self._lock:
                if not self._enabled:
                    return
                # 1. Look for an idle channel within current intensity limit
                for i in range(limit):
                    ch = self._channels[i]
                    if not ch.get_busy():
                        target_channel = ch
                        target_idx = i
                        break

                # 2. If all active channels are busy, steal the OLDEST channel
                if target_channel is None:
                    # Find channel in [0 .. limit) that was played furthest in the past
                    oldest_idx = 0
                    oldest_time = self._channel_timestamps[0]
                    for i in range(1, limit):
                        if self._channel_timestamps[i] < oldest_time:
                            oldest_time = self._channel_timestamps[i]
                            oldest_idx = i

                    target_channel = self._channels[oldest_idx]
                    target_idx = oldest_idx
                    # Immediate preemption: stop the oldest sound to free channel for newest keypress
                    target_channel.stop()

                # 3. Configure volume and play sound
                if volume is None:  # +/-6% loudness humanisation so repeats never match exactly
                    target_volume = min(1.0, self._calculate_channel_volume() * random.uniform(0.94, 1.06))
                else:
                    target_volume = max(0.0, min(1.0, volume))
                target_channel.set_volume(target_volume)
                target_channel.play(sound_obj)
                self._channel_timestamps[target_idx] = now

            # Notify GUI of keypress for visualization
            if self._on_key_played:
                try:
                    self._on_key_played(profile)
                except Exception as e:
                    logger.debug("on_key_played callback error: %s", e)

        except Exception as e:
            if not self._is_running:
                return
            logger.warning("Playback error: %s", e)
            self._attempt_recovery()

    def _attempt_recovery(self):
        """Attempts to recover from audio device disconnection or driver faults."""
        # Rate-limit so a dead device cannot cause a tight retry loop.
        now = time.monotonic()
        if now - self._last_recovery < 2.0:
            return
        self._last_recovery = now
        if not self._is_running:
            return
        logger.warning("Attempting audio device recovery...")
        self._device_healthy = False           # nothing may touch the mixer while it is rebuilt
        try:
            with self._lock:                   # short: only the mixer teardown/re-init
                if not self._is_running:
                    return
                time.sleep(0.05)
                ok = self._init_backend(mark_healthy=False)
            if ok and self._sound_manager is not None and self._is_running:
                self._sound_manager.reset_sounds()   # slow: done outside the lock
            if ok and self._is_running:
                self._device_healthy = True
        except Exception as e:
            self._device_healthy = False
            self._last_error = f"Recovery failed: {e}"
            logger.error(self._last_error)

    # --- Public API ---

    def trigger_key(self, vk_code: int):
        """
        Fast non-blocking handoff from keyboard hook.
        If queue is saturated during extreme flood, drops oldest or skips to prevent lag.
        """
        if not self._enabled or not self._device_healthy:
            return

        self._enqueue(vk_code, None, None)

    def trigger_sound(self, sound, volume: Optional[float] = None, vk_code: int = 0x41):
        """Plays an explicit pre-rendered Sound (used by the audio test tool). volume is 0.0-1.0."""
        if not self._device_healthy:
            return
        self._enqueue(vk_code, sound, volume)

    def trigger_test_meow(self):
        """Plays a sample meow (used by the Test Meow button)."""
        self.trigger_key(0x20)

    def _enqueue(self, vk_code, sound, volume):
        item = (time.perf_counter(), vk_code, sound, volume)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # Newest-event priority: discard the oldest pending event, keep the newest
            self._dropped_full += 1
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                self._queue.put_nowait(item)
            except Exception:
                pass

    def stop_all(self):
        """Immediately silences every channel and discards all pending events."""
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break
            except Exception:
                break
        with self._lock:
            for ch in self._channels:
                try:
                    ch.stop()
                except Exception:
                    pass
            if PYGAME_AVAILABLE:
                try:
                    if pygame.mixer.get_init():
                        pygame.mixer.stop()
                except Exception:
                    pass

    @property
    def pitch_mapper(self):
        return self._sound_manager._pitch_mapper if self._sound_manager is not None else None

    def device_info(self) -> dict:
        """Snapshot of the audio backend for the UI."""
        info = {"healthy": self._device_healthy, "error": self._last_error, "freq": 0,
                "channels": 0, "buffer_ms": 0.0, "limit": INTENSITY_CHANNELS.get(self._intensity, 12)}
        try:
            if self._device_healthy and PYGAME_AVAILABLE and pygame.mixer.get_init():
                freq, _fmt, ch = pygame.mixer.get_init()
                info.update(freq=freq, channels=ch, buffer_ms=round(DEFAULT_AUDIO_BUFFER / freq * 1000, 1))
        except Exception:
            pass
        return info

    def restart_audio(self):
        """Re-initialises the audio device in the background (e.g. after unplugging headphones)."""
        def _work():
            self._last_recovery = 0.0
            self._attempt_recovery()
        self._restart_thread = threading.Thread(target=_work, name="MeowAudioRestart", daemon=True)
        self._restart_thread.start()

    @property
    def pending_events(self) -> int:
        return self._queue.qsize()

    @property
    def dropped_events(self) -> int:
        return self._dropped_stale + self._dropped_full

    @property
    def active_channels(self) -> int:
        """Busy channels within the current limit. Non-blocking and safe during audio recovery."""
        if not self._device_healthy or not self._lock.acquire(blocking=False):
            return self._last_active if self._device_healthy else 0
        try:
            limit = INTENSITY_CHANNELS.get(self._intensity, 12)
            n = sum(1 for i in range(min(limit, len(self._channels))) if self._channels[i].get_busy())
            self._last_active = n
            return n
        except Exception:
            return 0
        finally:
            self._lock.release()

    def set_intensity(self, intensity: str):
        """Switches intensity mode (CHILL=4, NORMAL=12, CHAOS=24 channels)."""
        if intensity not in INTENSITY_CHANNELS:
            return
        with self._lock:
            self._intensity = intensity
            limit = INTENSITY_CHANNELS[intensity]
            for i in range(limit, len(self._channels)):   # silence channels beyond the new limit
                try:
                    if self._channels[i].get_busy():
                        self._channels[i].stop()
                except Exception:
                    pass
            logger.info("Switched intensity to %s (channels=%d)", intensity, limit)

    def set_personality(self, personality: str):
        """Switches active cat personality."""
        if self._sound_manager:
            self._sound_manager.set_personality(personality)

    def set_volume(self, volume: int):
        """Sets master volume (0 - 100)."""
        self._volume = max(0, min(100, int(volume)))
        scaled = self._calculate_channel_volume()
        with self._lock:
            limit = INTENSITY_CHANNELS.get(self._intensity, 12)
            for i in range(min(limit, len(self._channels))):
                try:
                    self._channels[i].set_volume(scaled)
                except Exception:
                    pass

    def set_enabled(self, enabled: bool):
        """Enables or disables sound. Disabling silences everything playing, immediately."""
        self._enabled = enabled
        if not enabled:
            self.stop_all()
        logger.info("AudioEngine enabled=%s", enabled)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def is_healthy(self) -> bool:
        return self._device_healthy

    @property
    def status_message(self) -> str:
        if not self._enabled:
            return "Engine Muted"
        if not self._device_healthy:
            return f"Audio Error: {self._last_error}"
        limit = INTENSITY_CHANNELS.get(self._intensity, 12)
        active_count = sum(1 for i in range(limit) if i < len(self._channels) and self._channels[i].get_busy())
        return f"Active ({active_count}/{limit} channels)"

    def shutdown(self):
        """Releases all audio resources."""
        self._is_running = False
        w = self._worker_thread
        if w is not None and w.is_alive() and w is not threading.current_thread():
            w.join(timeout=0.5)
        r = self._restart_thread
        if r is not None and r.is_alive() and r is not threading.current_thread():
            r.join(timeout=6.0)
        with self._lock:
            for ch in self._channels:
                try:
                    ch.stop()
                except Exception:
                    pass
            if PYGAME_AVAILABLE and pygame.mixer.get_init():
                try:
                    pygame.mixer.quit()
                except Exception:
                    pass
        logger.info("AudioEngine shut down cleanly")
