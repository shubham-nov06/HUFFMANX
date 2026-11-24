"""HuffmanX lossless, file-agnostic compression engine."""
from __future__ import annotations
import hashlib, json, struct, zlib
from collections import Counter

MAGIC=b'HFX1'

def _huffman_encode(data: bytes):
    if not data: return {'counts': [], 'bits': 0}, b''
    counts=Counter(data); heap=[]
    import heapq
    for i,(b,n) in enumerate(sorted(counts.items())): heapq.heappush(heap,(n,i, b, None, None))
    serial=len(heap)
    while len(heap)>1:
        a=heapq.heappop(heap); b=heapq.heappop(heap)
        heapq.heappush(heap,(a[0]+b[0],serial,None,a,b)); serial+=1
    codes={}
    def walk(node,p):
        if node[2] is not None: codes[node[2]]=p or '0'
        else: walk(node[3],p+'0'); walk(node[4],p+'1')
    walk(heap[0],'')
    bits=''.join(codes[x] for x in data); bitlen=len(bits); bits += '0' *((-len(bits))%8)
    payload=int(bits,2).to_bytes(len(bits)//8,'big') if bits else b''
    return {'counts': [[k,v] for k,v in sorted(counts.items())], 'bits':bitlen},payload

def _huffman_decode(meta,payload):
    counts={int(k):int(v) for k,v in meta['counts']}; total=sum(counts.values()); bitlen=int(meta['bits'])
    if total==0: return b''
    import heapq
    heap=[]
    for i,(k,v) in enumerate(sorted(counts.items())): heapq.heappush(heap,(v,i,k,None,None))
    serial=len(heap)
    while len(heap)>1:
        a=heapq.heappop(heap); b=heapq.heappop(heap); heapq.heappush(heap,(a[0]+b[0],serial,None,a,b)); serial+=1
    root=heap[0]
    if root[2] is not None:
        if bitlen!=total: raise ValueError('Invalid single-symbol Huffman stream')
        return bytes([root[2]])*total
    out=bytearray(); node=root
    for i in range(bitlen):
        bit=(payload[i//8]>>(7-i%8))&1; node=node[3] if bit==0 else node[4]
        if node[2] is not None:
            out.append(node[2]); node=root
            if len(out)>total: raise ValueError('Invalid Huffman stream')
    if node is not root or len(out)!=total: raise ValueError('Truncated Huffman stream')
    return bytes(out)

def _rle_encode(data):
    out=bytearray(); i=0
    while i<len(data):
        run=1
        while i+run<len(data) and data[i+run]==data[i] and run<255: run+=1
        out.extend((run,data[i])); i+=run
    return bytes(out)
def _rle_decode(data):
    if len(data)%2: raise ValueError('Corrupt RLE stream')
    out=bytearray()
    for i in range(0,len(data),2):
        if data[i]==0: raise ValueError('Invalid RLE run')
        out.extend(bytes([data[i+1]])*data[i])
    return bytes(out)


def _lz77_encode(data: bytes, window: int = 4095, lookahead: int = 255) -> bytes:
    """Bounded-candidate LZ77 encoder; avoids quadratic scans on large files."""
    out = bytearray()
    # Index positions by a 4-byte prefix. Keep only a bounded recent candidate set.
    chains = {}  # capped hash chains keep auxiliary memory bounded
    i = 0
    while i < len(data):
        best_len = 0
        best_dist = 0
        max_len = min(lookahead, len(data) - i)
        if max_len >= 4:
            key = data[i:i + 4]
            candidates = chains.get(key)
            if candidates:
                for j in reversed(candidates):
                    distance = i - j
                    if distance > window:
                        continue
                    length = 4
                    while length < max_len and data[j + (length % distance)] == data[i + length]:
                        length += 1
                    if length > best_len:
                        best_len, best_dist = length, distance
                    if best_len == max_len:
                        break
        consumed = best_len if best_len >= 4 else 1
        if best_len >= 4:
            out.append(1)
            out.extend(struct.pack('>HB', best_dist, best_len))
        else:
            out.extend((0, data[i]))
        # Index all positions consumed by this token so future matches can refer to them.
        for pos in range(i, min(i + consumed, len(data) - 3)):
            key = data[pos:pos + 4]
            q = chains.get(key)
            if q is None:
                if len(chains) >= 65536:
                    chains.pop(next(iter(chains)))
                q = chains[key] = []
            q.append(pos)
            if len(q) > 16:
                del q[0]
        i += consumed
    return bytes(out)

def _lz77_decode(data: bytes) -> bytes:
    out = bytearray(); i = 0
    while i < len(data):
        flag = data[i]; i += 1
        if flag == 0:
            if i >= len(data): raise ValueError('Truncated LZ77 literal')
            out.append(data[i]); i += 1
        elif flag == 1:
            if i + 3 > len(data): raise ValueError('Truncated LZ77 match')
            distance, length = struct.unpack('>HB', data[i:i+3]); i += 3
            if distance == 0 or distance > len(out) or length < 4:
                raise ValueError('Invalid LZ77 match')
            for _ in range(length): out.append(out[-distance])
        else: raise ValueError('Unknown LZ77 token')
    return bytes(out)

def _lzw_encode(data):
    if not data:return b''
    dictionary={bytes([i]):i for i in range(256)}; nxt=256; w=b''; codes=[]
    for c in data:
        wc=w+bytes([c])
        if wc in dictionary: w=wc
        else:
            codes.append(dictionary[w])
            if nxt<65535: dictionary[wc]=nxt; nxt+=1
            w=bytes([c])
    if w: codes.append(dictionary[w])
    return b''.join(struct.pack('>H',x) for x in codes)
def _lzw_decode(data):
    if len(data)%2: raise ValueError('Corrupt LZW stream')
    codes=[struct.unpack('>H',data[i:i+2])[0] for i in range(0,len(data),2)]
    if not codes:return b''
    d={i:bytes([i]) for i in range(256)}; nxt=256; old=codes[0]
    if old not in d: raise ValueError('Invalid LZW code')
    out=bytearray(d[old]); w=d[old]
    for k in codes[1:]:
        if k in d: entry=d[k]
        elif k==nxt: entry=w+w[:1]
        else: raise ValueError('Invalid LZW code sequence')
        out.extend(entry)
        if nxt<65535: d[nxt]=w+entry[:1]; nxt+=1
        w=entry
    return bytes(out)

CODECS=('auto','huffman','rle','lz77','lzw','deflate')
def compress_bytes(data: bytes, filename: str, codec='auto', progress_callback=None, checkpoint=None):
    if codec not in CODECS:
        raise ValueError('Unsupported algorithm')
    encoders = {
        'huffman': lambda: (lambda result: (result[1], result[0]))(_huffman_encode(data)),
        'rle': lambda: (_rle_encode(data), {}),
        'lz77': lambda: (_lz77_encode(data), {}),
        'lzw': lambda: (_lzw_encode(data), {}),
        'deflate': lambda: (zlib.compress(data, 9), {}),
    }
    names = list(encoders) if codec == 'auto' else [codec]
    candidates = {}
    for index, name in enumerate(names, 1):
        if checkpoint:
            checkpoint()
        if progress_callback:
            progress_callback(index - 1, len(names), name, 'running')
        candidates[name] = encoders[name]()
        if progress_callback:
            progress_callback(index, len(names), name, 'complete')
        if checkpoint:
            checkpoint()
    if codec == 'auto':
        digest = hashlib.sha256(data).hexdigest()
        def total_size(item):
            name, (candidate_payload, candidate_extra) = item
            candidate_meta = {'version': 1, 'filename': filename or 'restored_file.bin', 'codec': name,
                              'original_size': len(data), 'sha256': digest, 'extra': candidate_extra}
            return len(candidate_payload) + len(json.dumps(candidate_meta, separators=(',', ':')).encode()) + 8
        chosen = min(candidates.items(), key=total_size)[0]
    else:
        chosen = codec
    payload, extra = candidates[chosen]
    meta = {'version': 1, 'filename': filename or 'restored_file.bin', 'codec': chosen,
            'original_size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'extra': extra}
    header = json.dumps(meta, separators=(',', ':')).encode()
    blob = MAGIC + struct.pack('>I', len(header)) + header + payload
    stats = {'filename': meta['filename'], 'algorithm': chosen.upper(), 'original_bytes': len(data),
             'compressed_bytes': len(blob), 'payload_bytes': len(payload),
             'saved_percent': round((1 - len(blob) / len(data)) * 100, 2) if data else 0,
             'ratio': round(len(data) / len(blob), 3) if blob else 1,
             'sha256': meta['sha256'], 'note': 'Already-compressed or tiny files may not become smaller.'}
    return blob, stats

def decompress_bytes(blob:bytes):
    if len(blob)<8 or blob[:4]!=MAGIC: raise ValueError('Not a valid HuffmanX .hfx file')
    n=struct.unpack('>I',blob[4:8])[0]
    if n>1024*1024 or 8+n>len(blob): raise ValueError('Invalid or truncated HFX header')
    meta=json.loads(blob[8:8+n]); payload=blob[8+n:]; codec=meta['codec']
    if codec=='huffman': data=_huffman_decode(meta['extra'],payload)
    elif codec=='rle': data=_rle_decode(payload)
    elif codec=='lz77': data=_lz77_decode(payload)
    elif codec=='lzw': data=_lzw_decode(payload)
    elif codec=='deflate': data=zlib.decompress(payload)
    else: raise ValueError('Unknown compression algorithm')
    if len(data)!=meta['original_size']: raise ValueError('Restored size does not match metadata')
    if hashlib.sha256(data).hexdigest()!=meta['sha256']: raise ValueError('Integrity check failed: checksum mismatch')
    return data,meta
