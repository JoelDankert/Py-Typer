# Animalese asset extraction

`extract_animalese_assets.py` downloads the packaged Chrome extension for
`djbgadolfboockbofalipohdncimebic`, unpacks it, and copies any bundled audio
files into a local `sounds/` tree.

Run:

```bash
cd /mnt/drive2/tempdefault/git/Py-Typer
python3 extract_animalese_assets.py
```

Custom output directory:

```bash
python3 extract_animalese_assets.py --out ./animalese_dump
```

If `sounds/` ends up empty, the extension is likely generating audio or
storing it in a non-file format. In that case, inspect `unpacked/` and patch
the extension code to dump decoded audio buffers.
# Py-Typer
