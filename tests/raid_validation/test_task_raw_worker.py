"""The actual web worker's metadata-free RAID0/5 branch, known-byte oracle."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from .test_raw import raw_fixture

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not shutil.which("mkntfs"), reason="open-source NTFS formatter required")
@pytest.mark.parametrize("level,layout", [(0, 0), (5, 2)])
def test_web_worker_metadata_free_infer_prepare_matches_independent_image(tmp_path, level, layout):
    image = tmp_path / "known.ntfs"
    with image.open("wb") as out: out.truncate(16 * 1024**2)
    subprocess.run(["mkntfs", "-F", "-Q", "-q", "-s", "512", "-c", "4096", str(image)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    root, members, expected = raw_fixture(tmp_path, level=level, layout=layout, logical=image.read_bytes())
    members = [members[2], members[0], members[1]]
    def worker(action, data):
        source = tmp_path / (action + ".json"); source.write_text(json.dumps(data))
        process = subprocess.run([sys.executable, str(ROOT / "scripts/raid_web_worker.py"), action, str(source)],
            capture_output=True, text=True, timeout=240, check=False)
        assert process.returncode == 0, process.stderr
        return json.loads(process.stdout)
    data = {"source_root": str(root), "members": members}
    result = worker("infer", data)
    assert result["mode"] == "raw" and result["status"] in ("UNIQUE_STRUCTURAL_CANDIDATE", "AMBIGUOUS")
    known_plan = {"level": level, "layout": layout, "chunk_size": 4096, "order": [1, 2, 0], "data_offset": 0}
    chosen = next(c for c in result["candidates"] if c["plan"] == known_plan)
    output = tmp_path / "output"; output.mkdir()
    prepared = worker("prepare", {**data, "candidate": chosen, "mode": "raw", "allow_partial": False,
        "source_revision": result["source_revision"], "output_root": str(output), "max_bytes": 32 * 1024**2})
    assert prepared["status"] == "COMPLETE"
    assert (Path(prepared["package_directory"]) / "logical.img").read_bytes() == expected
