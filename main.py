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
DEBUG = True

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
    pitch_shift: float = 0.0
    pitch_variation: float = 0.02
    intonation: float = 0.0


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
        self.cache_dir = ROOT / ".sound_cache"
        self.cache_dir.mkdir(exist_ok=True)
        pygame.mixer.pre_init(frequency=48000, size=-16, channels=2, buffer=512)
        pygame.mixer.init()
        pygame.mixer.set_num_channels(32)
        self.cutoff_channels: dict[int, pygame.mixer.Channel] = {}
        self.sound_cache: dict[Path, pygame.mixer.Sound] = {}

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
            debug("skip: empty audio path")
            return

        file_path = self.extension_root / f"{relative_path}.aac"
        if not file_path.exists():
            debug(f"missing audio file: {file_path}")
            return

        profile = self.config.profile
        detune_cents = 0.0
        if use_profile or random_pitch or pitch:
            detune_cents = (profile.pitch_shift + pitch) * 100.0 if use_profile else pitch * 100.0
            spread = (profile.pitch_variation if use_profile else 0.0) + random_pitch
            detune_cents += random.uniform(-300.0, 300.0) * spread

        actual_volume = max(0.0, min(2.0, volume * self.config.volume * 0.95))
        debug(f"play key file={file_path} volume={actual_volume:.3f} detune={detune_cents:.2f}")

        with self.lock:
            sound = self._load_sound(file_path, detune_cents)
            if sound is None:
                return
            channel = self._get_channel(cutoff_channel)
            channel.set_volume(actual_volume)
            channel.play(sound)

    def _get_channel(self, cutoff_channel: int) -> pygame.mixer.Channel:
        if cutoff_channel:
            channel = self.cutoff_channels.get(cutoff_channel)
            if channel is None:
                channel = pygame.mixer.Channel(cutoff_channel - 1)
                self.cutoff_channels[cutoff_channel] = channel
            else:
                channel.stop()
            return channel

        channel = pygame.mixer.find_channel(force=True)
        if channel is None:
            channel = pygame.mixer.Channel(31)
        return channel

    def _load_sound(self, file_path: Path, detune_cents: float) -> pygame.mixer.Sound | None:
        if abs(detune_cents) < 0.01:
            cached = self.sound_cache.get(file_path)
            if cached is not None:
                return cached
            wav_path = self._cached_wav_path(file_path)
            if not wav_path.exists() and not self._convert_to_wav(file_path, wav_path):
                return None
            sound = pygame.mixer.Sound(str(wav_path))
            self.sound_cache[file_path] = sound
            return sound

        wav_bytes = self._render_shifted_wav(file_path, detune_cents)
        if wav_bytes is None:
            return None
        return pygame.mixer.Sound(buffer=wav_bytes)

    def _cached_wav_path(self, file_path: Path) -> Path:
        rel = file_path.relative_to(self.extension_root)
        return self.cache_dir / rel.with_suffix(".wav")

    def _convert_to_wav(self, file_path: Path, wav_path: Path) -> bool:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(file_path),
            "-ar",
            "48000",
            str(wav_path),
        ]
        debug(f"decode cache cmd={' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            debug(f"ffmpeg decode failed: {result.stderr.strip()}")
            return False
        return True

    def _render_shifted_wav(self, file_path: Path, detune_cents: float) -> bytes | None:
        factor = 2 ** (detune_cents / 1200.0)
        filters = [f"asetrate=48000*{factor:.6f}", "aresample=48000"]
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
        debug(f"render shifted cmd={' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip()
            debug(f"ffmpeg render failed: {stderr}")
            return None
        return result.stdout


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
        debug(f"key event raw={key!r}")
        resolved = resolve_key(key)
        if not resolved:
            debug("key ignored: unresolved")
            return
        debug(f"resolved key={resolved!r}")
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


def debug(message: str) -> None:
    if DEBUG:
        print(f"[debug] {message}", flush=True)


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
    pitch_variation = ask_float("Pitch variation", 0.02)
    pitch_shift = ask_float("Pitch shift", 0.0)
    intonation = ask_float("Intonation", 0.0)

    config = AppConfig(
        gender=gender,
        voice_type=f"voice_{voice_choice}",
        volume=volume,
        sound_config={"1": 0, "2": 1, "3": 2}[mode_choice],
        profile=SoundProfile(
            pitch_shift=pitch_shift,
            pitch_variation=pitch_variation,
            intonation=intonation,
        ),
    )

    print()
    print("Current config")
    print(f"  Gender: {config.gender}")
    print(f"  Voice: {labels[int(voice_choice) - 1]} ({config.voice_type})")
    print(f"  Mode: {MODE_LABELS[config.sound_config]}")
    print(f"  Volume: {config.volume}")
    print(f"  Pitch variation: {config.profile.pitch_variation}")
    print(f"  Pitch shift: {config.profile.pitch_shift}")
    print(f"  Intonation: {config.profile.intonation}")
    input("Press Enter to start...")
    return config


def main() -> int:
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    config = build_config()
    AnimaleseTyper(config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
