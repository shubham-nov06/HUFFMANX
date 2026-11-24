import sys, os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import pytest
from engine import compress_bytes,decompress_bytes,CODECS

@pytest.mark.parametrize('codec',CODECS)
@pytest.mark.parametrize('data',[b'',b'a',b'aaaaaa',b'hello world',bytes(range(256)),b'ABCD'*1000, 'HuffmanX • नमस्ते • 漢字'.encode()])
def test_binary_roundtrip(codec,data):
    blob,stats=compress_bytes(data,'sample.bin',codec)
    restored,meta=decompress_bytes(blob)
    assert restored==data
    assert meta['filename']=='sample.bin'
    assert stats['original_bytes']==len(data)

def test_auto_selects_a_codec():
    blob,_=compress_bytes(b'abcde'*500,'repeat.txt','auto')
    _,meta=decompress_bytes(blob)
    assert meta['codec'] in CODECS[1:]

def test_corrupt_magic_rejected():
    with pytest.raises(ValueError): decompress_bytes(b'nope')

def test_truncated_header_rejected():
    with pytest.raises(ValueError): decompress_bytes(b'HFX1\x00\x00\x00\x20{}')

def test_checksum_detects_payload_corruption():
    blob,_=compress_bytes(b'hello world'*100,'x.txt','deflate')
    broken=bytearray(blob); broken[-1]^=1
    with pytest.raises((ValueError, Exception)): decompress_bytes(bytes(broken))

def test_api_upload_compress_and_restore():
    from fastapi.testclient import TestClient
    from main import app
    import base64
    client=TestClient(app)
    original=b'API integration payload ' * 40
    response=client.post('/api/compress',files={'file':('integration.txt',original,'text/plain')},data={'algorithm':'auto'})
    assert response.status_code==200
    body=response.json()
    archive=base64.b64decode(body['compressed_base64'])
    restored=client.post('/api/decompress',files={'file':('integration.hfx',archive,'application/octet-stream')})
    assert restored.status_code==200
    assert restored.content==original
    assert restored.headers.get('x-integrity-verified')=='true'

def test_lz77_roundtrip():
    from backend.engine import compress_bytes, decompress_bytes
    data=(b'ABRACADABRA-'*200)+bytes(range(256))
    blob, stats=compress_bytes(data,'sample.bin','lz77')
    restored, meta=decompress_bytes(blob)
    assert restored == data
    assert meta['codec'] == 'lz77'

def test_lz77_empty_and_single_byte():
    from backend.engine import compress_bytes, decompress_bytes
    for data in (b'', b'x', b'aaaaaaaaaaaaaaaa', bytes(range(256))):
        blob,_=compress_bytes(data,'x.bin','lz77')
        assert decompress_bytes(blob)[0] == data
