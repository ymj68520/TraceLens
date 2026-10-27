import hashlib
import importlib.util
from pathlib import Path
import shutil
import struct
import pytest
from httpserver.services.xiaomi_image import ExportImage, ImageError, inspect_header
from httpserver.services.evidence_preflight import _probe

spec = importlib.util.spec_from_file_location('xiaomi_fixture', Path(__file__).resolve().parents[3] / 'tests/integration/xiaomi_fixture.py')
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
pytestmark = pytest.mark.skipif(not shutil.which('mke2fs'), reason='requires synthetic EXT4 builder')


@pytest.fixture
def image(tmp_path): return fixture.build(tmp_path)


def test_export_layout_index_and_unchanged_source(image):
    before = hashlib.sha256(image.read_bytes()).hexdigest()
    assert _probe(image)['adapter'] == 'xiaomi-image'
    rows = []
    with ExportImage(image) as source: source.index(rows.append)
    files = {r['path']: r for r in rows if r['type'] == 'file'}
    assert files['/data/com.android.providers.contacts/databases/contacts2.db']['readable']
    assert files['/storage/emulated/0/DCIM/fixture.txt']['readable']
    bad = files['/DMF/fixture.dmf']
    assert not bad['readable'] and '重叠' in bad['error'] and not bad['runs']
    assert next(r for r in rows if r['type'] == 'meta')['manifest']['source_sha256'] == before
    assert hashlib.sha256(image.read_bytes()).hexdigest() == before
    assert rows[-1]['type'] == 'complete'


def test_truncated_image_rejected(image):
    with image.open('r+b') as f: f.truncate(image.stat().st_size - 4096)
    assert not inspect_header(image)['candidate']


def test_source_change_during_index_rejected(image):
    def receive(row):
        if row['type'] == 'meta':
            with image.open('r+b') as f: f.seek(100); f.write(b'changed')
    with ExportImage(image) as source, pytest.raises(ImageError, match='变化'):
        source.index(receive)


def test_extent_bounds_fail_closed(image):
    with ExportImage(image) as source:
        _, raw = source.inode(2)
        corrupt = bytearray(raw)
        struct.pack_into('<I', corrupt, 60, 0xffffffff)
        with pytest.raises(ImageError, match='越界'):
            source.runs(corrupt)


def test_directory_cycles_and_unsafe_components_rejected(image):
    with ExportImage(image) as source:
        block = source.runs(source.inode(2)[1])[0][1]
    # Replace the DMF directory name with an unsafe component of the same length.
    with image.open('r+b') as f:
        f.seek(block); data = bytearray(f.read(4096)); at = data.index(b'DMF'); data[at:at+3] = b'a/b'
        f.seek(block); f.write(data)
    assert not inspect_header(image)['candidate']


def test_regular_ext4_without_export_markers_is_not_xiaomi(tmp_path):
    import subprocess
    image = tmp_path / 'ordinary.bin'
    with image.open('wb') as f: f.truncate(16 << 20)
    subprocess.run(['mke2fs', '-q', '-F', '-t', 'ext4', str(image)], check=True)
    assert not inspect_header(image)['candidate']
    assert _probe(image)['kind'] == 'raw_image_candidate'
