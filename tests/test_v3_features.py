import base64
import io
import threading
import time
import zipfile

from fastapi.testclient import TestClient
from backend.main import app, _job_checkpoint, JobCancelled
from backend.engine import compress_bytes, decompress_bytes

client = TestClient(app)


def wait_for_job(job_id, timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f'/api/jobs/{job_id}')
        assert response.status_code == 200
        body = response.json()
        if body['status'] in ('completed', 'failed', 'cancelled'):
            return body
        time.sleep(0.025)
    raise AssertionError('Background compression job timed out')


def test_background_single_file_job_roundtrip():
    original = (b'HuffmanX background queue\x00' * 100)
    started = client.post('/api/jobs/compress', files={'file': ('job.bin', original, 'application/octet-stream')}, data={'algorithm': 'auto'})
    assert started.status_code == 200
    job = wait_for_job(started.json()['id'])
    assert job['status'] == 'completed' and job['progress'] == 100
    packed = base64.b64decode(job['result']['compressed_base64'])
    assert decompress_bytes(packed)[0] == original


def test_background_batch_job_preserves_directories_and_encryption():
    files = [
        ('files', ('docs/readme.txt', b'hello from huffmanx', 'text/plain')),
        ('files', ('assets/pixel.bin', bytes(range(64)), 'application/octet-stream')),
    ]
    started = client.post('/api/jobs/compress-batch', files=files, data={'algorithm': 'auto', 'password': 'secure-test-pass'})
    assert started.status_code == 200
    job = wait_for_job(started.json()['id'])
    assert job['status'] == 'completed'
    bundle = base64.b64decode(job['result']['archive_base64'])
    restored = client.post('/api/decompress-batch', files={'file': ('locked.hfxlock', bundle, 'application/octet-stream')}, data={'password': 'secure-test-pass'})
    assert restored.status_code == 200
    with zipfile.ZipFile(io.BytesIO(restored.content)) as archive:
        assert archive.read('docs/readme.txt') == b'hello from huffmanx'
        assert archive.read('assets/pixel.bin') == bytes(range(64))


def test_pause_and_cancel_checkpoints_are_cooperative():
    job = {'cancel_requested': False, 'resume_event': threading.Event(), 'status': 'paused'}
    completed = threading.Event()
    thread = threading.Thread(target=lambda: (_job_checkpoint(job), completed.set()), daemon=True)
    thread.start()
    assert not completed.wait(0.05), 'Paused job should block at a safe checkpoint'
    job['resume_event'].set()
    assert completed.wait(1), 'Resumed job should leave the checkpoint'

    job2 = {'cancel_requested': True, 'resume_event': threading.Event(), 'status': 'running'}
    job2['resume_event'].set()
    try:
        _job_checkpoint(job2)
        assert False, 'Cancelled job must raise JobCancelled'
    except JobCancelled:
        pass


def test_job_control_rejects_invalid_actions():
    assert client.post('/api/jobs/not-a-real-job/pause').status_code == 404


def test_visualizer_supplies_real_encode_and_decode_steps():
    original = b'abracadabra'
    response = client.post('/api/visualize', files={'file': ('sample.txt', original, 'text/plain')})
    assert response.status_code == 200
    body = response.json()
    assert len(body['encoding_steps']) == len(original)
    assert len(body['decoding_steps']) == len(original)
    assert ''.join(x['code'] for x in body['encoding_steps']) == body['sample_bitstream']
    assert bytes(x['decoded_byte'] for x in body['decoding_steps']) == original


def test_integrity_endpoint_detects_different_bytes():
    response = client.post('/api/integrity/compare', files=[
        ('original', ('a.bin', b'abc', 'application/octet-stream')),
        ('restored', ('b.bin', b'abd', 'application/octet-stream')),
    ])
    assert response.status_code == 200
    assert response.json()['identical'] is False
    assert response.json()['sha256_match'] is False


def test_lz77_roundtrip_on_random_and_large_repeated_data():
    import random
    random.seed(42)
    for original in (bytes(random.randrange(256) for _ in range(20000)), b'Z' * 150000, (b'abc123' * 10000)):
        packed, _ = compress_bytes(original, 'stress.bin', 'lz77')
        assert decompress_bytes(packed)[0] == original


def test_job_control_endpoints_pause_resume_and_cancel_flags():
    from backend.main import _JOBS, _JOBS_LOCK
    job_id = 'unit-control-job'
    fake = {
        'id': job_id, 'kind': 'single', 'status': 'running', 'progress': 20,
        'stage': 'running', 'current_file': 'x.txt', 'file_index': 0,
        'file_count': 1, 'codec': 'HUFFMAN', 'message': '',
        'created_at': time.time(), 'updated_at': time.time(),
        'cancel_requested': False, 'resume_event': threading.Event(), 'result': None, 'error': None,
    }
    fake['resume_event'].set()
    with _JOBS_LOCK:
        _JOBS[job_id] = fake
    try:
        paused = client.post(f'/api/jobs/{job_id}/pause')
        assert paused.status_code == 200 and paused.json()['status'] == 'paused'
        assert not fake['resume_event'].is_set()
        resumed = client.post(f'/api/jobs/{job_id}/resume')
        assert resumed.status_code == 200 and resumed.json()['status'] == 'running'
        assert fake['resume_event'].is_set()
        cancelled = client.post(f'/api/jobs/{job_id}/cancel')
        assert cancelled.status_code == 200 and fake['cancel_requested'] is True
    finally:
        with _JOBS_LOCK:
            _JOBS.pop(job_id, None)


def test_batch_rejects_duplicate_paths():
    response = client.post('/api/compress-batch', files=[
        ('files', ('same.txt', b'one', 'text/plain')),
        ('files', ('same.txt', b'two', 'text/plain')),
    ])
    assert response.status_code == 400


def test_batch_rejects_parent_segment_even_if_normalization_would_hide_it():
    response = client.post('/api/compress-batch', files=[
        ('files', ('folder/../safe.txt', b'no path tricks', 'text/plain')),
    ])
    assert response.status_code == 400


def test_job_paused_before_worker_start_stays_paused_until_resumed():
    from backend.main import _run_job
    job = {
        'id': 'paused-start-test', 'kind': 'single', 'status': 'paused', 'progress': 0,
        'stage': 'paused', 'current_file': 'tiny.txt', 'file_index': 0, 'file_count': 1,
        'codec': '', 'message': 'Paused at startup', 'created_at': time.time(), 'updated_at': time.time(),
        'cancel_requested': False, 'resume_event': threading.Event(), 'result': None, 'error': None,
    }
    worker = threading.Thread(target=_run_job, args=(job, (b'paused startup', 'tiny.txt', 'auto')), daemon=True)
    worker.start()
    time.sleep(0.05)
    assert job['status'] == 'paused' and worker.is_alive()
    job['resume_event'].set()
    worker.join(timeout=2)
    assert job['status'] == 'completed'
