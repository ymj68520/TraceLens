#!/usr/bin/env python3
"""Install the checksum-pinned SenseVoice STT + silero VAD models.

Layout produced (consumed by
python_service/httpserver/services/llm/audio_analyzer.py):

    python_service/models/audio/
    ├── silero_vad.onnx
    └── sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/
        ├── model.int8.onnx
        └── tokens.txt

Sources are the model authors' own distribution channels: the SenseVoice
ONNX export repo on HuggingFace and the sherpa-onnx GitHub release for the
VAD model. Every artifact is SHA256-pinned; a mismatch aborts without
installing. No evidence content is uploaded by this installer or by the
STT runtime. Honors HTTP(S)_PROXY environment variables (setup.sh exports
them from PIP_PROXY).
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "python_service" / "models" / "audio"
MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
MODEL_DIR = AUDIO_DIR / MODEL_NAME

SENSE_VOICE_URL_BASE = (
    "https://huggingface.co/csukuangfj/"
    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main"
)
SILERO_VAD_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
)

# (path relative to AUDIO_DIR, url, sha256)
ARTIFACTS = [
    (f"{MODEL_NAME}/model.int8.onnx",
     f"{SENSE_VOICE_URL_BASE}/model.int8.onnx",
     "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51"),
    (f"{MODEL_NAME}/tokens.txt",
     f"{SENSE_VOICE_URL_BASE}/tokens.txt",
     "f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc"),
    ("silero_vad.onnx",
     SILERO_VAD_URL,
     "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"),
]

MANUAL_HINT = (
    "Manual alternative: fetch the artifacts above, or the full k2-fsa release "
    "tarball https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2, and place "
    f"model.int8.onnx + tokens.txt under {MODEL_DIR} and silero_vad.onnx under {AUDIO_DIR}"
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def missing_artifacts() -> list[tuple[str, str, str]]:
    todo = []
    for rel, url, sha in ARTIFACTS:
        target = AUDIO_DIR / rel
        if target.is_file() and sha256_of(target) == sha:
            continue
        todo.append((rel, url, sha))
    return todo


def fetch(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "tracelens-setup"})
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)


def install() -> None:
    todo = missing_artifacts()
    if not todo:
        print(f"Audio STT models ready: {AUDIO_DIR}")
        return
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for rel, url, sha in todo:
        target = AUDIO_DIR / rel
        if target.exists():
            # Present but different content: replace, never keep unverified bytes.
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {rel} ...")
        # Temp inside AUDIO_DIR keeps the final replace on one filesystem.
        with tempfile.TemporaryDirectory(prefix="stt-model-", dir=AUDIO_DIR) as temp_name:
            artifact = Path(temp_name) / "artifact"
            fetch(url, artifact)
            if sha256_of(artifact) != sha:
                raise RuntimeError(f"Checksum mismatch for {rel} ({url})")
            artifact.replace(target)
        print(f"Installed {rel}")
    print(f"Audio STT models installed: {AUDIO_DIR}")


if __name__ == "__main__":
    try:
        install()
    except Exception as exc:  # noqa: BLE001 - single entry point, report and fail
        print(f"Audio STT model installation failed: {exc}", file=sys.stderr)
        print(MANUAL_HINT, file=sys.stderr)
        sys.exit(1)
