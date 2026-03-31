#!/usr/bin/env python3
from __future__ import annotations

import json
import random
import re
import signal
import subprocess
import sys
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pygame
from pynput import keyboard as pynput_keyboard


ROOT = Path(__file__).resolve().parent
EXTENSION_ROOT = ROOT / "animalese_extension_dump" / "unpacked"
ASSETS_ROOT = EXTENSION_ROOT / "assets" / "audio"
LOCALE_FILE = EXTENSION_ROOT / "_locales" / "en" / "messages.json"
SOUND_CACHE_VERSION = "v3"
CLICK_FADE_SECONDS = 0.003
CLICK_FADE_MS = max(1, int(CLICK_FADE_SECONDS * 1000))
MIXER_FREQUENCY = 44100
MIXER_BUFFER = 4096
VOLUME_VARIATION = 0.08

FEMALE_LABELS = ["Sweet", "Peppy", "Big sister", "Snooty"]
MALE_LABELS = ["Jock", "Lazy", "Smug", "Cranky"]
MODE_LABELS = {
    0: "All",
    1: "Animalese only",
    2: "Soundfx only",
}

PHONETIC_MAP = {
    "a": ["à", "á", "â", "ã", "ä", "å", "æ", "ā", "ă", "ą", "ǎ"],
    "b": ["ḃ", "ḅ", "ḇ"],
    "c": ["ç", "ć", "ĉ", "ċ", "č"],
    "d": ["ď", "đ", "ḋ", "ḍ", "ḏ", "ḑ", "ḓ"],
    "e": ["è", "é", "ê", "ë", "ē", "ĕ", "ė", "ę", "ě", "ẹ", "ẻ", "ẽ", "ế", "ề", "ể", "ễ", "ệ", "ğ"],
    "f": ["ẟ"],
    "g": ["ĝ", "ğ", "ġ", "ģ", "ḡ"],
    "h": ["ĥ", "ȟ", "ḥ", "ḧ", "ḩ", "ḫ", "ẖ"],
    "i": ["ì", "í", "î", "ï", "ĩ", "ī", "ĭ", "į", "ı", "ỉ", "ị"],
    "j": ["ĵ", "ǰ"],
    "k": ["ķ", "ḱ", "ḳ", "ḵ", "ƙ"],
    "l": ["ĺ", "ļ", "ľ", "ŀ", "ł", "ḷ", "ḹ", "ḻ", "ḽ"],
    "m": ["ḿ", "ṁ", "ṃ"],
    "n": ["ñ", "ń", "ņ", "ň", "ŉ", "ŋ", "ṇ", "ṉ", "ṋ"],
    "o": ["ò", "ó", "ô", "õ", "ö", "ø", "ō", "ŏ", "ő", "ơ", "ǫ", "ǭ", "ọ", "ỏ", "ố", "ồ", "ổ", "ỗ", "ộ", "ớ", "ờ", "ở", "ỡ", "ợ"],
    "p": ["ṕ", "ṗ"],
    "q": ["ɋ"],
    "r": ["ŕ", "ŗ", "ř", "ȑ", "ȓ", "ṙ", "ṛ", "ṝ", "ṟ"],
    "s": ["ß", "ś", "ŝ", "ş", "š", "ṡ", "ṣ", "ṥ", "ṧ", "ṩ", "ẛ"],
    "t": ["ţ", "ť", "ŧ", "ṫ", "ṭ", "ṯ", "ṱ", "ẗ"],
    "u": ["ù", "ú", "û", "ü", "ũ", "ū", "ŭ", "ů", "ű", "ų", "ư", "ṳ", "ṵ", "ṷ", "ṹ", "ṻ", "ụ", "ủ", "ứ", "ừ", "ử", "ữ", "ự"],
    "v": ["ṿ", "ʋ"],
    "w": ["ŵ", "ẁ", "ẃ", "ẅ", "ẇ", "ẉ", "ẘ"],
    "x": ["ẋ", "ẍ"],
    "y": ["ý", "ÿ", "ŷ", "ȳ", "ẏ", "ẙ", "ỳ", "ỵ", "ỷ", "ỹ"],
    "z": ["ź", "ż", "ž", "ẑ", "ẓ", "ẕ", "ȥ"],
}
REVERSE_PHONETIC_MAP = {
    char: phoneme for phoneme, chars in PHONETIC_MAP.items() for char in chars
}


@dataclass
class SoundProfile:
    pass


@dataclass
class AppConfig:
    gender: str = "female"
    voice_type: str = "voice_1"
    volume: float = 0.5
    sound_config: int = 0
    profile: SoundProfile = field(default_factory=SoundProfile)


class AudioEngine:
    def __init__(self, extension_root: Path, config: AppConfig) -> None:
        self.extension_root = extension_root
        self.config = config
        self.lock = threading.Lock()
        self.cache_dir = ROOT / f".sound_cache_{SOUND_CACHE_VERSION}"
        self.cache_dir.mkdir(exist_ok=True)
        pygame.mixer.pre_init(
            frequency=MIXER_FREQUENCY,
            size=-16,
            channels=2,
            buffer=MIXER_BUFFER,
            allowedchanges=pygame.AUDIO_ALLOW_ANY_CHANGE,
        )
        pygame.mixer.init(
            frequency=MIXER_FREQUENCY,
            size=-16,
            channels=2,
            buffer=MIXER_BUFFER,
            allowedchanges=pygame.AUDIO_ALLOW_ANY_CHANGE,
        )
        pygame.mixer.set_num_channels(32)
        self.cutoff_channels: dict[int, pygame.mixer.Channel] = {}
        self.sound_cache: dict[tuple[Path, int], pygame.mixer.Sound] = {}

    def cleanup(self) -> None:
        with self.lock:
            pygame.mixer.stop()
            pygame.mixer.quit()

    def play(
        self,
        relative_path: str | None,
        volume: float,
        random_pitch: float = 0.0,
        pitch: float = 0.0,
        cutoff_channel: int = 0,
        use_profile: bool = False,
    ) -> None:
        if not relative_path:
            return

        file_path = self.extension_root / f"{relative_path}.aac"
        if not file_path.exists():
            return

        detune_cents = 0.0

        volume_scale = 1.0 + random.uniform(-VOLUME_VARIATION, VOLUME_VARIATION)
        actual_volume = max(0.0, min(2.0, volume * self.config.volume * 0.95 * volume_scale))

        with self.lock:
            sound = self._load_sound(file_path, detune_cents)
            if sound is None:
                return
            channel = self._get_channel(cutoff_channel)
            channel.set_volume(actual_volume)
            channel.play(sound, fade_ms=CLICK_FADE_MS)

    def _get_channel(self, cutoff_channel: int) -> pygame.mixer.Channel:
        if cutoff_channel:
            channel = self.cutoff_channels.get(cutoff_channel)
            if channel is None:
                channel = pygame.mixer.Channel(cutoff_channel - 1)
                self.cutoff_channels[cutoff_channel] = channel
            else:
                channel.fadeout(CLICK_FADE_MS)
            return channel

        channel = pygame.mixer.find_channel(force=True)
        if channel is None:
            channel = pygame.mixer.Channel(31)
        return channel

    def _load_sound(self, file_path: Path, detune_cents: float) -> pygame.mixer.Sound | None:
        cache_key = (file_path, int(round(detune_cents)))
        if abs(detune_cents) < 0.01:
            cached = self.sound_cache.get(cache_key)
            if cached is not None:
                return cached
            wav_path = self._cached_wav_path(file_path)
            if not wav_path.exists() and not self._convert_to_wav(file_path, wav_path):
                return None
            sound = pygame.mixer.Sound(str(wav_path))
            self.sound_cache[cache_key] = sound
            return sound

        cached = self.sound_cache.get(cache_key)
        if cached is not None:
            return cached
        wav_bytes = self._render_shifted_wav(file_path, detune_cents)
        if wav_bytes is None:
            return None
        sound = pygame.mixer.Sound(buffer=wav_bytes)
        self.sound_cache[cache_key] = sound
        return sound

    def _cached_wav_path(self, file_path: Path) -> Path:
        rel = file_path.relative_to(self.extension_root)
        return self.cache_dir / rel.with_suffix(".wav")

    def _convert_to_wav(self, file_path: Path, wav_path: Path) -> bool:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        duration = self._probe_duration(file_path)
        filters = self._build_fade_filters(duration)
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(file_path),
            "-af",
            filters,
            "-ar",
            str(MIXER_FREQUENCY),
            str(wav_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return False
        return True

    def _render_shifted_wav(self, file_path: Path, detune_cents: float) -> bytes | None:
        factor = 2 ** (detune_cents / 1200.0)
        duration = self._probe_duration(file_path)
        filters = [
            f"asetrate={MIXER_FREQUENCY}*{factor:.6f}",
            f"aresample={MIXER_FREQUENCY}",
            *self._build_fade_filter_parts(duration),
        ]
        cmd = [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            str(file_path),
            "-filter:a",
            ",".join(filters),
            "-f",
            "wav",
            "-",
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            return None
        return result.stdout

    def _probe_duration(self, file_path: Path) -> float | None:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        try:
            return float(result.stdout.strip())
        except ValueError:
            return None

    def _build_fade_filters(self, duration: float | None) -> str:
        return ",".join(self._build_fade_filter_parts(duration))

    def _build_fade_filter_parts(self, duration: float | None) -> list[str]:
        fade = CLICK_FADE_SECONDS
        if duration is not None:
            fade = min(CLICK_FADE_SECONDS, max(duration / 4.0, 0.0))

        filters = [f"afade=t=in:st=0:d={fade:.6f}"]
        if duration is not None and duration > 0:
            out_start = max(duration - fade, 0.0)
            filters.append(f"afade=t=out:st={out_start:.6f}:d={fade:.6f}")
        return filters


class AnimaleseTyper:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.audio = AudioEngine(EXTENSION_ROOT, config)
        self.listener: pynput_keyboard.Listener | None = None

    def run(self) -> None:
        print()
        print("Running globally.")
        print("Press q and Enter in this terminal to stop.")
        print()

        try:
            self.listener = pynput_keyboard.Listener(on_press=self._handle_key_event)
            self.listener.start()
        except Exception as exc:
            raise SystemExit(f"Failed to start global listener: {exc}") from exc
        try:
            while True:
                user_input = input().strip().lower()
                if user_input == "q":
                    break
        finally:
            if self.listener is not None:
                self.listener.stop()
            self.audio.cleanup()

    def _handle_key_event(self, key: pynput_keyboard.Key | pynput_keyboard.KeyCode) -> None:
        resolved = resolve_key(key)
        if not resolved:
            return
        self._process_key(resolved)

    def _process_key(self, key: str) -> None:
        cfg = self.config.sound_config

        if key in {" ", "ctrl", "alt", "shift", "caps lock"}:
            return

        if cfg != 1 and key in {"left", "up", "right", "down"}:
            mapping = {
                "left": "assets/audio/sfx/arrow_left",
                "up": "assets/audio/sfx/arrow_up",
                "right": "assets/audio/sfx/arrow_right",
                "down": "assets/audio/sfx/arrow_down",
            }
            self.audio.play(mapping[key], 0.4)
            return

        if cfg != 1 and key in {"backspace", "delete"}:
            self.audio.play("assets/audio/sfx/backspace", 1.0)
            return

        if cfg != 1 and key == "enter":
            self.audio.play("assets/audio/sfx/enter", 0.2)
            return

        if cfg != 1 and key == "tab":
            self.audio.play("assets/audio/sfx/tab", 0.5)
            return

        if key == "?":
            if cfg != 1:
                self.audio.play("assets/audio/sfx/question", 0.6)
            if cfg != 2:
                self.audio.play(self._animalese_base("Deska"), 0.6, 0.2, 0.0, 1, True)
            return

        if key == "!":
            if cfg != 1:
                self.audio.play("assets/audio/sfx/exclamation", 0.6)
            if cfg != 2:
                self.audio.play(self._animalese_base("Gwah"), 0.6, 0.2, 0.0, 1, True)
            return

        if cfg != 2 and key in "1234567890":
            idx = "1234567890".index(key)
            self.audio.play(self._vocal_base(str(idx)), 1.0)
            return

        letter = get_letter_sound(key)
        if cfg != 2 and letter:
            if letter.isupper():
                self.audio.play(self._animalese_base(letter.lower()), 0.65, 0.02, 0.35, 1, True)
            else:
                self.audio.play(self._animalese_base(letter), 0.5, 0.0, 0.0, 1, True)
            return

        if cfg != 1:
            self.audio.play("assets/audio/sfx/default", 0.4, 0.4)

    def _animalese_base(self, name: str) -> str:
        return f"assets/audio/animalese/{self.config.gender}/{self.config.voice_type}/{name}"

    def _vocal_base(self, name: str) -> str:
        return f"assets/audio/vocals/{self.config.gender}/{self.config.voice_type}/{name}"


def resolve_key(key: pynput_keyboard.Key | pynput_keyboard.KeyCode) -> str | None:
    if isinstance(key, pynput_keyboard.KeyCode):
        if key.char:
            return key.char
        return None

    special_map = {
        pynput_keyboard.Key.space: " ",
        pynput_keyboard.Key.left: "left",
        pynput_keyboard.Key.right: "right",
        pynput_keyboard.Key.up: "up",
        pynput_keyboard.Key.down: "down",
        pynput_keyboard.Key.backspace: "backspace",
        pynput_keyboard.Key.delete: "delete",
        pynput_keyboard.Key.enter: "enter",
        pynput_keyboard.Key.tab: "tab",
        pynput_keyboard.Key.shift: "shift",
        pynput_keyboard.Key.shift_l: "shift",
        pynput_keyboard.Key.shift_r: "shift",
        pynput_keyboard.Key.ctrl: "ctrl",
        pynput_keyboard.Key.ctrl_l: "ctrl",
        pynput_keyboard.Key.ctrl_r: "ctrl",
        pynput_keyboard.Key.alt: "alt",
        pynput_keyboard.Key.alt_l: "alt",
        pynput_keyboard.Key.alt_r: "alt",
        pynput_keyboard.Key.caps_lock: "caps lock",
    }
    return special_map.get(key)


def get_letter_sound(key: str) -> str | None:
    if len(key) != 1:
        return None
    if re.fullmatch(r"[a-zA-Z]", key):
        return key

    if key in REVERSE_PHONETIC_MAP:
        phoneme = REVERSE_PHONETIC_MAP[key]
        return phoneme.upper() if key.isupper() else phoneme

    normalized = unicodedata.normalize("NFKD", key)
    ascii_letters = [ch for ch in normalized if re.fullmatch(r"[a-zA-Z]", ch)]
    return ascii_letters[0] if ascii_letters else None


def load_voice_labels() -> tuple[list[str], list[str]]:
    if not LOCALE_FILE.exists():
        return FEMALE_LABELS, MALE_LABELS
    try:
        data = json.loads(LOCALE_FILE.read_text(encoding="utf-8"))
        female = [data[f"f_voice_{i}"]["message"] for i in range(1, 5)]
        male = [data[f"m_voice_{i}"]["message"] for i in range(1, 5)]
        return female, male
    except Exception:
        return FEMALE_LABELS, MALE_LABELS


def ask_choice(prompt: str, options: dict[str, str], default: str) -> str:
    print()
    print(prompt)
    for key, label in options.items():
        print(f"  {key}. {label}")
    while True:
        value = input(f"Select [{default}]: ").strip() or default
        if value in options:
            return value
        print("Invalid selection.")


def ask_float(prompt: str, default: float) -> float:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            print("Enter a number.")


def build_config() -> AppConfig:
    if not ASSETS_ROOT.exists():
        raise SystemExit(f"Missing assets directory: {ASSETS_ROOT}")

    female_labels, male_labels = load_voice_labels()
    gender_choice = ask_choice(
        "Select gender",
        {"1": "Female", "2": "Male"},
        "1",
    )
    gender = "female" if gender_choice == "1" else "male"

    labels = female_labels if gender == "female" else male_labels
    voice_choice = ask_choice(
        "Select voice",
        {str(index): label for index, label in enumerate(labels, start=1)},
        "1",
    )

    mode_choice = ask_choice(
        "Select sound mode",
        {"1": "All", "2": "Animalese only", "3": "Soundfx only"},
        "2",
    )

    volume = ask_float("Volume 0.0-1.0", 0.5)
    config = AppConfig(
        gender=gender,
        voice_type=f"voice_{voice_choice}",
        volume=volume,
        sound_config={"1": 0, "2": 1, "3": 2}[mode_choice],
        profile=SoundProfile(),
    )

    print()
    print("Current config")
    print(f"  Gender: {config.gender}")
    print(f"  Voice: {labels[int(voice_choice) - 1]} ({config.voice_type})")
    print(f"  Mode: {MODE_LABELS[config.sound_config]}")
    print(f"  Volume: {config.volume}")
    input("Press Enter to start...")
    return config


def main() -> int:
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    config = build_config()
    AnimaleseTyper(config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
