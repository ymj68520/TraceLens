import shutil
import pytest
from httpserver.services import android_lp_image as lp

def test_frozen_lp_bundle_needs_no_git_but_rejects_source_and_binary_tampering(tmp_path,monkeypatch):
    original=lp.tool_root()
    bundle=tmp_path/'bundle'
    shutil.copytree(original,bundle)
    monkeypatch.setattr(lp,'tool_root',lambda:bundle)
    assert lp.verify_tools()==bundle/'bin'
    manifest=bundle/'pinned-source.sha256'
    first=manifest.read_text().splitlines()[0].split('  ',1)[1]
    source=bundle/first
    before=source.read_bytes()
    source.write_bytes(before+b'\n')
    with pytest.raises(lp.LpError,match='SOURCE_PIN_MISMATCH'): lp.verify_tools()
    source.write_bytes(before)
    binary=bundle/'bin/liblp.so'
    binary.write_bytes(binary.read_bytes()+b'X')
    with pytest.raises(lp.LpError,match='BINARY_PIN_MISMATCH'): lp.verify_tools()
