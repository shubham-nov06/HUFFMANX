from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_health_endpoint():
    r=client.get('/api/health')
    assert r.status_code==200 and r.json()['status']=='ok'

def test_compare_endpoint_returns_all_algorithms():
    r=client.post('/api/compare', files={'file':('sample.txt',b'abracadabra'*20,'text/plain')})
    assert r.status_code==200
    body=r.json()
    assert {x['algorithm'] for x in body['results']}=={'HUFFMAN','RLE','LZ77','LZW','DEFLATE'}
    assert body['best']==body['results'][0]['algorithm']

def test_visualize_endpoint_builds_huffman_merges():
    r=client.post('/api/visualize', files={'file':('sample.txt',b'aaabbc','text/plain')})
    assert r.status_code==200
    body=r.json()
    assert body['unique_symbols']==3
    assert len(body['merges'])==2
    assert sum(x['frequency'] for x in body['frequencies'])==6

def test_batch_endpoint_creates_zip_of_hfx_files():
    r=client.post('/api/compress-batch', files=[('files',('a.txt',b'alpha','text/plain')),('files',('b.bin',b'\x00\xff','application/octet-stream'))])
    assert r.status_code==200
    body=r.json()
    assert len(body['files'])==2
    import base64,io,zipfile
    z=zipfile.ZipFile(io.BytesIO(base64.b64decode(body['archive_base64'])))
    assert sorted(z.namelist())==['HuffmanX-manifest.json','a.txt.hfx','b.bin.hfx']

def test_batch_rejects_unknown_codec():
    r=client.post('/api/compress-batch', data={'algorithm':'nope'}, files=[('files',('a.txt',b'x','text/plain'))])
    assert r.status_code==400


def test_folder_batch_preserves_subfolders_and_restores_original_bytes():
    import base64, io, zipfile
    files=[('files',('Project/src/main.py',b'print("hello")\n','text/plain')),('files',('Project/assets/data.bin',bytes(range(256))*4,'application/octet-stream'))]
    compressed=client.post('/api/compress-batch',files=files)
    assert compressed.status_code==200
    payload=base64.b64decode(compressed.json()['archive_base64'])
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        assert 'Project/src/main.py.hfx' in z.namelist()
        assert 'Project/assets/data.bin.hfx' in z.namelist()
    restored=client.post('/api/decompress-batch',files={'file':('folder.hfxzip',payload,'application/zip')})
    assert restored.status_code==200
    with zipfile.ZipFile(io.BytesIO(restored.content)) as z:
        assert z.read('Project/src/main.py')==b'print("hello")\n'
        assert z.read('Project/assets/data.bin')==bytes(range(256))*4

def test_batch_rejects_path_traversal():
    r=client.post('/api/compress-batch',files=[('files',('../escape.txt',b'nope','text/plain'))])
    assert r.status_code==400

def test_smart_analyzer_and_preview_endpoints():
    a=client.post('/api/analyze',files={'file':('notes.txt',b'hello hello hello','text/plain')})
    assert a.status_code==200 and a.json()['recommendation'] in {'HUFFMAN','RLE','LZ77','LZW','DEFLATE'}
    p=client.post('/api/preview',files={'file':('notes.txt',b'hello','text/plain')})
    assert p.status_code==200 and p.json()['text_preview']=='hello'

def test_benchmark_reports_time_and_memory():
    r=client.post('/api/benchmark',files={'file':('sample.txt',b'abc'*40,'text/plain')})
    assert r.status_code==200
    assert len(r.json()['results'])==5
    assert all(x['elapsed_ms']>=0 and x['peak_memory_bytes']>=0 for x in r.json()['results'])

def test_integrity_compare_checks_byte_identity():
    r=client.post('/api/integrity/compare',files=[('original',('a.bin',b'abc','application/octet-stream')),('restored',('b.bin',b'abc','application/octet-stream'))])
    assert r.status_code==200 and r.json()['identical'] and r.json()['sha256_match']

def test_password_protected_batch_round_trip():
    import base64
    c=client.post('/api/compress-batch',data={'password':'correct-horse-battery'},files=[('files',('docs/a.txt',b'private data','text/plain'))])
    assert c.status_code==200 and c.json()['password_protected']
    blob=base64.b64decode(c.json()['archive_base64'])
    denied=client.post('/api/decompress-batch',files={'file':('bundle.hfxlock',blob,'application/octet-stream')})
    assert denied.status_code==400
    restored=client.post('/api/decompress-batch',data={'password':'correct-horse-battery'},files={'file':('bundle.hfxlock',blob,'application/octet-stream')})
    assert restored.status_code==200
    import io,zipfile
    with zipfile.ZipFile(io.BytesIO(restored.content)) as z: assert z.read('docs/a.txt')==b'private data'
