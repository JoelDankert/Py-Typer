#!/usr/bin/env python3
"""Download and extract bundled audio assets from the Animalese Typing extension.

This targets the Chrome extension package directly by extension ID so the output
matches the packaged extension more closely than scraping a repo snapshot.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


EXTENSION_ID = "djbgadolfboockbofalipohdncimebic"
UPDATE_URL = (
    "https://clients2.google.com/service/update2/crx"
    "?response=redirect"
    "&prodversion=131.0.0.0"
    "&acceptformat=crx2,crx3"
    f"&x=id%3D{EXTENSION_ID}%26uc"
)
SOUND_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".opus", ".webm"}


def download(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def crx_to_zip_bytes(data: bytes) -> bytes:
    if data[:2] == b"PK":
        return data
    if data[:4] != b"Cr24":
        raise ValueError("Downloaded file is neither ZIP nor CRX.")

    version = int.from_bytes(data[4:8], "little")
    if version == 2:
        pub_len = int.from_bytes(data[8:12], "little")
        sig_len = int.from_bytes(data[12:16], "little")
        header_len = 16 + pub_len + sig_len
    elif version == 3:
        header_len = 12 + int.from_bytes(data[8:12], "little")
    else:
        raise ValueError(f"Unsupported CRX version: {version}")

    zip_bytes = data[header_len:]
    if zip_bytes[:2] != b"PK":
        raise ValueError("CRX payload does not contain a ZIP archive.")
    return zip_bytes


def extract_archive(zip_bytes: bytes, extract_dir: Path) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        zf.extractall(extract_dir)


def copy_audio_files(source_dir: Path, target_dir: Path) -> list[Path]:
    copied: list[Path] = []
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in source_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOUND_EXTENSIONS:
            continue
        rel = path.relative_to(source_dir)
        dest = target_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied.append(dest)
    return copied


def load_manifest(extract_dir: Path) -> dict | None:
    manifest = extract_dir / "manifest.json"
    if not manifest.exists():
        return None
    return json.loads(manifest.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="animalese_extension_dump",
        help="Output directory for the unpacked extension and copied sounds.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    unpacked_dir = out_dir / "unpacked"
    sounds_dir = out_dir / "sounds"

    try:
        crx_data = download(UPDATE_URL)
        zip_bytes = crx_to_zip_bytes(crx_data)
        extract_archive(zip_bytes, unpacked_dir)
        copied = copy_audio_files(unpacked_dir, sounds_dir)
        manifest = load_manifest(unpacked_dir)
    except urllib.error.URLError as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 1

    print(f"Unpacked extension into: {unpacked_dir}")
    if manifest:
        print(
            "Manifest:",
            manifest.get("name", "<unknown>"),
            manifest.get("version", "<unknown>"),
        )

    if copied:
        print(f"Copied {len(copied)} audio files into: {sounds_dir}")
        for path in copied[:50]:
            print(path.relative_to(out_dir))
        if len(copied) > 50:
            print(f"... and {len(copied) - 50} more")
    else:
        print("No bundled audio files found. The extension may synthesize or embed audio differently.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
