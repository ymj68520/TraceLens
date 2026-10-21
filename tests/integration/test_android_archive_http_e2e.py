"""Real HTTP task admission and extraction for synthetic dir/ZIP/TAR/7z/AB."""
import argparse
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time

from test_android_container_cli_e2e import (
    build_tree, package_sources, encrypted_ab_bytes, counts, EXPECTED, assert_artifact_content,
)
from test_android_filesystem_http_e2e import request, await_task
from httpserver.services import evidence_preflight as preflight


def run(analyzer):
    with tempfile.TemporaryDirectory(prefix='tracelens_archive_http_') as directory:
        root = Path(directory)
        runtime = root / 'runtime'
        runtime.mkdir()
        (root / 'logical').mkdir()
        sources = package_sources(root, build_tree(root / 'logical'))
        encrypted = root / 'encrypted.ab'
        encrypted.write_bytes(encrypted_ab_bytes(sources['tar'].read_bytes(), 'fixture-secret'))
        sources['encrypted-ab'] = encrypted
        hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest()
                  for key, path in sources.items() if path.is_file()}
        preflight.evidence_inbox = lambda: root.resolve()
        preflight.job_root = lambda: runtime / 'evidence_preflight'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        with (root / 'server.log').open('w') as log:
            server = subprocess.Popen([str(analyzer), '--http-server', str(port)],
                env=dict(os.environ, DATA_DIR=str(runtime), LLM_ENABLED='false', GRAPHITI_ENABLED='false'),
                stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    try:
                        if request(base + '/api/system/health')[0] == 200: break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise AssertionError('isolated server did not start')
                for mode, source in sources.items():
                    payload = dict(image_path=str(source), android_source=mode,
                                   scenarios=['android'], platform_analyze=True, llm_analyze=False)
                    if mode == 'encrypted-ab':
                        payload.update(android_source='android-backup', backup_password='fixture-secret')
                    if mode not in {'dir', 'zip'}:
                        candidate = next(c for c in preflight.list_candidates() if c['name'] == source.name)
                        job_id = preflight.start_job(candidate['id'], full_hash=True,
                            password='fixture-secret' if mode == 'encrypted-ab' else '')['id']
                        deadline = time.monotonic() + 90
                        while time.monotonic() < deadline:
                            job = preflight.get_job(job_id)
                            if job['status'] not in {'queued', 'running'}: break
                            time.sleep(0.1)
                        assert job['status'] == 'completed', job
                        payload.update(preflight_job_id=job_id, preflight_source_sha256=job['sha256'],
                                       preflight_detected_kind=job['detected']['kind'])
                    code, created = request(base + '/api/tasks', payload)
                    assert code == 201, (mode, code, created)
                    task = await_task(base, created['id'])
                    assert task['status'].lower() == 'completed', (mode, task)
                    db = Path(task['output_files_db'])
                    assert counts(db) == EXPECTED, mode
                    assert_artifact_content(db)
                    assert 'fixture-secret' not in str(task)
                assert all(hashlib.sha256(sources[k].read_bytes()).hexdigest() == v for k,v in hashes.items())
                print({'modes': list(sources), 'counts': EXPECTED, 'source_hashes_unchanged': True})
            except Exception:
                log.flush()
                print((root / 'server.log').read_text()[-4000:])
                raise
            finally:
                server.terminate()
                try: server.wait(timeout=10)
                except subprocess.TimeoutExpired: server.kill(); server.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--analyzer', type=Path, required=True)
    run(parser.parse_args().analyzer.resolve(strict=True))
