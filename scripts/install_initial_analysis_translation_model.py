#!/usr/bin/env python3
"""Install the pinned offline EN→ZH Argos model into build/models.

The model archive comes from Argos' public package index and contains an
OPUS-MT model licensed CC-BY 4.0 (see the extracted README.md). No evidence
content is uploaded by this installer or by the translation runtime.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = "translate-en_zh-1_9"
MODEL_PARENT = ROOT / "build" / "models"
MODEL_DIR = MODEL_PARENT / MODEL_NAME
URL = "https://argos-net.com/v1/translate-en_zh-1_9.argosmodel"
SHA256 = "433e7c4f034d87fbe2353161e05f18646d7999452f801a4e1f0378522b9850ab"


def installed() -> bool:
    return (MODEL_DIR / "model" / "model.bin").is_file() and (
        MODEL_DIR / "sentencepiece.model"
    ).is_file()


def install() -> None:
    if installed():
        print(f"Offline EN-ZH model ready: {MODEL_DIR}")
        return
    if MODEL_DIR.exists():
        raise RuntimeError(f"Incomplete model directory exists; inspect it before reinstalling: {MODEL_DIR}")
    MODEL_PARENT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="en-zh-install-", dir=MODEL_PARENT) as temp_name:
        temp = Path(temp_name)
        archive = temp / "model.argosmodel"
        digest = hashlib.sha256()
        # argos-net.com rejects the default Python-urllib user agent with 403.
        request = urllib.request.Request(URL, headers={"User-Agent": "tracelens-setup"})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != SHA256:
            raise RuntimeError("Offline translation model checksum mismatch")
        with zipfile.ZipFile(archive) as model_zip:
            for member in model_zip.infolist():
                path = PurePosixPath(member.filename)
                if not path.parts or path.parts[0] != MODEL_NAME or ".." in path.parts:
                    raise RuntimeError("Model archive has an unsafe path")
            model_zip.extractall(temp / "unpacked")
        extracted = temp / "unpacked" / MODEL_NAME
        if not (extracted / "model" / "model.bin").is_file() or not (
            extracted / "sentencepiece.model"
        ).is_file():
            raise RuntimeError("Model archive lacks the translation weights or tokenizer")
        shutil.move(str(extracted), str(MODEL_DIR))
    print(f"Offline EN-ZH model installed: {MODEL_DIR}")


if __name__ == "__main__":
    install()
