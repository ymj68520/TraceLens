import hashlib
import shutil

import pytest

from httpserver.services import android_lp_image as lp


# The frozen bundle is built by scripts/install_android_container_tools.sh from
# pinned AOSP sources and lives in the git-ignored .deps/ tree. It is a build
# prerequisite of the LP coverage, so a missing bundle fails with the command to
# run rather than silently skipping the tamper-detection probe.
def _bundle_present() -> bool:
    root = lp.tool_root()
    return (root.is_dir() and (root / "bin" / "liblp.so").is_file()
            and (root / "pinned-source.sha256").is_file())


@pytest.fixture(autouse=True)
def _require_bundle():
    if not _bundle_present():
        pytest.fail(
            "AOSP LP toolchain missing; build it with "
            "./scripts/install_android_container_tools.sh",
            pytrace=False,
        )


def _copy_bundle(original, destination):
    """Copy the manifest plus every file it covers.

    The pinned sources are a sparse git checkout that contains dangling
    .clang-format symlinks pointing at files outside the sparse set; a plain
    copytree fails on them, and they play no part in the verification.
    """
    destination.mkdir()
    shutil.copy2(original / 'pinned-source.sha256', destination / 'pinned-source.sha256')
    for line in (original / 'pinned-source.sha256').read_text(encoding='utf-8').splitlines():
        relative = line.split('  ', 1)[1]
        # Entries outside the bundle (the inventory helper under scripts/) are
        # resolved against the project root by verify_tools and are not copied.
        if (original / relative).is_file():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original / relative, target)
    return destination


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    original = lp.tool_root()
    copy = _copy_bundle(original, tmp_path / 'bundle')
    monkeypatch.setattr(lp, 'tool_root', lambda: copy)
    assert lp.verify_tools() == copy / 'bin'
    return copy


def test_frozen_lp_bundle_needs_no_git_but_rejects_source_and_binary_tampering(bundle):
    manifest = bundle / 'pinned-source.sha256'
    first = manifest.read_text().splitlines()[0].split('  ', 1)[1]
    source = bundle / first
    before = source.read_bytes()
    source.write_bytes(before + b'\n')
    with pytest.raises(lp.LpError, match='SOURCE_PIN_MISMATCH'):
        lp.verify_tools()
    source.write_bytes(before)
    binary = bundle / 'bin/liblp.so'
    binary.write_bytes(binary.read_bytes() + b'X')
    with pytest.raises(lp.LpError, match='BINARY_PIN_MISMATCH'):
        lp.verify_tools()


def test_manifest_cannot_drop_an_audited_source(bundle):
    # Re-signing the manifest with one entry removed must not narrow the
    # accepted source set: the digest of the sorted source entries is pinned.
    manifest = bundle / 'pinned-source.sha256'
    lines = manifest.read_text().splitlines()
    manifest.write_text('\n'.join(lines[1:]) + '\n')
    with pytest.raises(lp.LpError, match='SOURCE_PIN_MISMATCH'):
        lp.verify_tools()


def test_manifest_cannot_add_an_unaudited_source(bundle):
    # A forged entry whose digest matches a real file still fails, because the
    # source set itself is pinned rather than merely self-consistent.
    extra = bundle / 'core/fs_mgr/liblp/extra.cpp'
    extra.write_text('int x;\n')
    digest = hashlib.sha256(extra.read_bytes()).hexdigest()
    with (bundle / 'pinned-source.sha256').open('a') as handle:
        handle.write(f'{digest}  core/fs_mgr/liblp/extra.cpp\n')
    with pytest.raises(lp.LpError, match='SOURCE_PIN_MISMATCH'):
        lp.verify_tools()


def test_missing_binary_is_rejected(bundle):
    (bundle / 'bin/lpunpack').unlink()
    with pytest.raises(lp.LpError, match='BINARY_PIN_MISMATCH'):
        lp.verify_tools()
