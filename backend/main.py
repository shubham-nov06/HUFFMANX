from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
import io, zipfile, posixpath, hashlib, time, tracemalloc, mimetypes, threading, uuid, base64
try:
    from .engine import compress_bytes, decompress_bytes, CODECS
except ImportError:
    from engine import compress_bytes, decompress_bytes, CODECS
import json
app=FastAPI(title='HuffmanX API',description='Local-first lossless file compression and interactive DSA laboratory.',version='3.0.0')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
MAX_FILE=100*1024*1024
@app.get('/api/health')
def health(): return {'status':'ok','service':'HuffmanX','version':'3.0.0','algorithms':list(CODECS)}
@app.post('/api/compress')
async def compress(file:UploadFile=File(...),algorithm:str=Form('auto')):
    try:
        if algorithm not in CODECS: raise ValueError('Unknown algorithm')
        data=await file.read(MAX_FILE+1)
        if len(data)>MAX_FILE: raise ValueError('File exceeds 100 MB limit')
        blob,stats=compress_bytes(data,file.filename or 'upload.bin',algorithm)
        return {'filename':(file.filename or 'file')+'.hfx','compressed_base64':__import__('base64').b64encode(blob).decode(),'stats':stats}
    except Exception as e: raise HTTPException(400,str(e))
@app.post('/api/decompress')
async def decompress(file:UploadFile=File(...)):
    try:
        blob=await file.read(MAX_FILE+2*1024*1024)
        if len(blob)>MAX_FILE+2*1024*1024: raise ValueError('Compressed file is too large')
        data,meta=decompress_bytes(blob)
        return Response(data,media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="{meta["filename"].replace(chr(34), "")}"','X-Integrity-Verified':'true'})
    except Exception as e: raise HTTPException(400,str(e))

@app.post('/api/compare')
async def compare(file: UploadFile=File(...)):
    data=await file.read(MAX_FILE+1)
    if len(data)>MAX_FILE: raise HTTPException(400,'File exceeds 100 MB limit')
    results=[]
    for name in ('huffman','rle','lz77','lzw','deflate'):
        blob,stats=compress_bytes(data,file.filename or 'upload.bin',name)
        results.append({'algorithm':name.upper(),'compressed_bytes':len(blob),'saved_percent':stats['saved_percent'],'ratio':stats['ratio']})
    results.sort(key=lambda x:x['compressed_bytes'])
    return {'original_bytes':len(data),'results':results,'best':results[0]['algorithm']}

@app.post('/api/visualize')
async def visualize(file: UploadFile=File(...)):
    data=await file.read(MAX_FILE+1)
    if len(data)>MAX_FILE: raise HTTPException(400,'File exceeds 100 MB limit')
    from collections import Counter
    import heapq
    freq=Counter(data)
    heap=[]; serial=0
    for byte,count in sorted(freq.items()):
        heapq.heappush(heap,(count,serial,{'symbol':byte,'frequency':count,'leaf':True})); serial+=1
    merges=[]
    while len(heap)>1:
        a=heapq.heappop(heap); b=heapq.heappop(heap)
        node={'symbol':None,'frequency':a[0]+b[0],'leaf':False,'left':a[2],'right':b[2]}
        merges.append({'left_frequency':a[0],'right_frequency':b[0],'merged_frequency':a[0]+b[0]})
        heapq.heappush(heap,(node['frequency'],serial,node)); serial+=1
    codes={}
    def walk(n,p=''):
        if n is None:return
        if n['leaf']: codes[str(n['symbol'])]=p or '0'
        else: walk(n['left'],p+'0'); walk(n['right'],p+'1')
    root=heap[0][2] if heap else None
    walk(root)
    sample = list(data[:16])
    encoding_steps = [{'index': i + 1, 'byte': b, 'display': chr(b) if 32 <= b < 127 else f'0x{b:02X}', 'code': codes.get(str(b), '0')} for i, b in enumerate(sample)]
    decoding_steps = [{'index': x['index'], 'bits': x['code'], 'decoded_byte': x['byte'], 'display': x['display'], 'tree_path': list(x['code'])} for x in encoding_steps]
    return {'size':len(data),'unique_symbols':len(freq),'frequencies':[{'byte':b,'display':chr(b) if 32<=b<127 else f'0x{b:02X}','frequency':c,'code':codes[str(b)]} for b,c in sorted(freq.items(),key=lambda x:(-x[1],x[0]))[:256]],'merges':merges,'tree':root,'encoding_steps':encoding_steps,'decoding_steps':decoding_steps,'sample_bitstream':''.join(x['code'] for x in encoding_steps)}

def _safe_archive_path(name: str) -> str:
    """Normalize browser-relative paths and reject traversal/absolute paths."""
    name = (name or "file.bin").replace("\\", "/")
    if any(part == ".." for part in name.split("/")):
        raise ValueError("Unsafe file path in batch archive")
    normalized = posixpath.normpath(name)
    if normalized in ("", ".") or normalized.startswith("../") or normalized == ".." or normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        raise ValueError("Unsafe file path in batch archive")
    return normalized

@app.post('/api/compress-batch')
async def compress_batch(files:list[UploadFile]=File(...),algorithm:str=Form('auto'),password:str=Form('')):
    if algorithm not in CODECS: raise HTTPException(400,'Unknown algorithm')
    if not files: raise HTTPException(400,'Choose at least one file')
    if len(files)>500: raise HTTPException(400,'Maximum 500 files per folder/batch')
    buffer=io.BytesIO(); manifest=[]; total=0; seen_paths=set()
    try:
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            for item in files:
                relative = _safe_archive_path(item.filename or 'file.bin')
                if relative in seen_paths: raise ValueError(f'Duplicate path in batch: {relative}')
                seen_paths.add(relative)
                data=await item.read(MAX_FILE+1)
                if len(data)>MAX_FILE: raise ValueError(f'{relative} exceeds 100 MB limit')
                total += len(data)
                if total > MAX_FILE: raise ValueError('Combined batch size exceeds 100 MB limit')
                blob,stats=compress_bytes(data,relative,algorithm)
                archive.writestr(relative+'.hfx',blob)
                manifest.append({'filename':relative,'original_bytes':len(data),'compressed_bytes':len(blob),'algorithm':stats['algorithm']})
            archive.writestr('HuffmanX-manifest.json',json.dumps({'format':'HuffmanX batch v1','files':manifest},indent=2))
    except Exception as e:
        raise HTTPException(400,str(e))
    archive_bytes=buffer.getvalue(); filename='huffmanx-batch.hfxzip'
    if password:
        if len(password)<8: raise HTTPException(400,'Bundle password must be at least 8 characters')
        try:
            from cryptography.fernet import Fernet
            import base64, os
            salt=os.urandom(16); key=base64.urlsafe_b64encode(hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1,dklen=32))
            archive_bytes=b'HFXE1'+salt+Fernet(key).encrypt(archive_bytes); filename='huffmanx-batch.hfxlock'
        except ImportError: raise HTTPException(500,'Install cryptography to enable password-protected bundles')
    return {'archive_base64':__import__('base64').b64encode(archive_bytes).decode(),'filename':filename,'files':manifest,'total_original_bytes':total,'folder_structure_preserved':True,'password_protected':bool(password)}

@app.post('/api/decompress-batch')
async def decompress_batch(file:UploadFile=File(...),password:str=Form('')):
    raw=await file.read(MAX_FILE+10*1024*1024)
    if len(raw)>MAX_FILE+10*1024*1024: raise HTTPException(400,'Batch archive exceeds size limit')
    if raw.startswith(b'HFXE1'):
        if not password: raise HTTPException(400,'This bundle is password-protected')
        try:
            from cryptography.fernet import Fernet, InvalidToken
            import base64
            salt=raw[5:21]; key=base64.urlsafe_b64encode(hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1,dklen=32))
            raw=Fernet(key).decrypt(raw[21:])
        except Exception: raise HTTPException(400,'Incorrect password or damaged encrypted bundle')
    source=io.BytesIO(raw); output=io.BytesIO(); restored=[]; total=0; seen_targets=set()
    try:
        with zipfile.ZipFile(source,'r') as incoming, zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as outgoing:
            entries=[x for x in incoming.infolist() if not x.is_dir() and x.filename.lower().endswith('.hfx')]
            if not entries: raise ValueError('No .hfx files found in this batch archive')
            if len(entries)>500: raise ValueError('Maximum 500 files per archive')
            for entry in entries:
                if entry.file_size>MAX_FILE+2*1024*1024: raise ValueError('A compressed entry exceeds the size limit')
                compressed=incoming.read(entry)
                data,meta=decompress_bytes(compressed)
                total += len(data)
                if total>MAX_FILE: raise ValueError('Combined restored size exceeds 100 MB limit')
                target=_safe_archive_path(meta.get('filename') or entry.filename[:-4])
                if target in seen_targets: raise ValueError(f'Duplicate restored path: {target}')
                seen_targets.add(target)
                outgoing.writestr(target,data)
                restored.append({'filename':target,'bytes':len(data),'sha256_verified':True})
    except Exception as e:
        raise HTTPException(400,f'Batch restore failed: {e}')
    return Response(output.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="huffmanx-restored-folder.zip"','X-Integrity-Verified':'true','X-Restored-Files':str(len(restored))})



@app.post('/api/analyze')
async def analyze_file(file: UploadFile=File(...)):
    data=await file.read(MAX_FILE+1)
    if len(data)>MAX_FILE: raise HTTPException(400,'File exceeds 100 MB limit')
    from collections import Counter
    sample=data[:min(len(data),256*1024)]
    entropy=0.0
    if sample:
        counts=Counter(sample); n=len(sample)
        import math
        entropy=-sum((c/n)*math.log2(c/n) for c in counts.values())
    results=[]
    for name in ('huffman','rle','lz77','lzw','deflate'):
        blob,stats=compress_bytes(data,file.filename or 'upload.bin',name)
        results.append({'algorithm':name.upper(),'output_bytes':len(blob),'saved_percent':stats['saved_percent']})
    best=min(results,key=lambda x:x['output_bytes'])
    ext=(file.filename or '').lower().rsplit('.',1)[-1] if '.' in (file.filename or '') else ''
    precompressed={'jpg','jpeg','png','webp','gif','mp3','mp4','mkv','zip','gz','pdf','7z','rar','flac','aac'}
    return {'filename':file.filename,'size_bytes':len(data),'extension':ext,'sample_entropy_bits':round(entropy,3),'recommendation':best['algorithm'],'results':sorted(results,key=lambda x:x['output_bytes']),'already_compressed_hint':ext in precompressed,'message':'Already-compressed formats often gain little or no extra reduction. Auto mode selects the smallest measured output for this file.'}

@app.post('/api/integrity/compare')
async def integrity_compare(original:UploadFile=File(...),restored:UploadFile=File(...)):
    a=await original.read(MAX_FILE+1); b=await restored.read(MAX_FILE+1)
    if len(a)>MAX_FILE or len(b)>MAX_FILE: raise HTTPException(400,'Each file must be at most 100 MB')
    ah=hashlib.sha256(a).hexdigest(); bh=hashlib.sha256(b).hexdigest()
    return {'identical':a==b,'same_size':len(a)==len(b),'original_size':len(a),'restored_size':len(b),'original_sha256':ah,'restored_sha256':bh,'sha256_match':ah==bh}

@app.post('/api/benchmark')
async def benchmark(file:UploadFile=File(...)):
    data=await file.read(MAX_FILE+1)
    if len(data)>MAX_FILE: raise HTTPException(400,'File exceeds 100 MB limit')
    results=[]
    for name in ('huffman','rle','lz77','lzw','deflate'):
        tracemalloc.start(); started=time.perf_counter()
        blob,stats=compress_bytes(data,file.filename or 'benchmark.bin',name)
        elapsed=(time.perf_counter()-started)*1000; _,peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
        results.append({'algorithm':name.upper(),'output_bytes':len(blob),'elapsed_ms':round(elapsed,3),'peak_memory_bytes':peak,'saved_percent':stats['saved_percent']})
    return {'input_bytes':len(data),'results':results,'fastest':min(results,key=lambda x:x['elapsed_ms'])['algorithm'],'smallest':min(results,key=lambda x:x['output_bytes'])['algorithm'],'note':'Memory is Python-traced peak allocation, not total process RAM.'}

@app.post('/api/preview')
async def preview_file(file:UploadFile=File(...)):
    data=await file.read(2*1024*1024+1)
    if len(data)>2*1024*1024: raise HTTPException(400,'Preview limit is 2 MB')
    name=file.filename or 'file'; mime=file.content_type or mimetypes.guess_type(name)[0] or 'application/octet-stream'
    textual=mime.startswith('text/') or name.lower().endswith(('.json','.xml','.py','.js','.css','.html','.md','.csv','.java','.cpp'))
    preview=data.decode('utf-8',errors='replace')[:12000] if textual else None
    return {'filename':name,'mime_type':mime,'size_bytes':len(data),'text_preview':preview,'hex_preview':None if textual else data[:128].hex(' '),'preview_supported':textual}


# ---------------- Background job orchestration ----------------
# Jobs are intentionally in-memory: this is a local single-process learning app.
# Pause/cancel are cooperative checkpoints between codec passes and between files.
_JOBS = {}
_JOBS_LOCK = threading.Lock()
_JOB_LIMIT = 20

class JobCancelled(Exception):
    pass


def _job_checkpoint(job):
    if job['cancel_requested']:
        raise JobCancelled('Compression cancelled by user')
    job['resume_event'].wait()
    if job['cancel_requested']:
        raise JobCancelled('Compression cancelled by user')
    if job['status'] == 'paused':
        job['status'] = 'running'


def _job_progress(job, done, total, codec, state):
    job['codec'] = codec.upper()
    job['stage'] = state
    # Scale codec stages into an overall percentage; batch workers add file offsets.
    job['progress'] = min(99, int((job['file_index'] + done / max(1, total)) / max(1, job['file_count']) * 100))
    job['updated_at'] = time.time()


def _public_job(job):
    return {k: job[k] for k in ('id', 'kind', 'status', 'progress', 'stage', 'current_file', 'file_index', 'file_count', 'codec', 'message', 'created_at', 'updated_at')}


def _new_job(kind, worker_data):
    with _JOBS_LOCK:
        if len(_JOBS) >= 60:
            finished = sorted((x for x in _JOBS.values() if x['status'] in ('completed', 'failed', 'cancelled')), key=lambda x: x['updated_at'])
            for old in finished[:max(0, len(_JOBS) - 40)]:
                _JOBS.pop(old['id'], None)
        active = sum(1 for x in _JOBS.values() if x['status'] in ('queued', 'running', 'paused'))
        if active >= _JOB_LIMIT:
            raise HTTPException(429, 'Too many active jobs. Finish or cancel another job first.')
        job_id = uuid.uuid4().hex
        job = {'id': job_id, 'kind': kind, 'status': 'queued', 'progress': 0, 'stage': 'queued',
               'current_file': '', 'file_index': 0, 'file_count': 1, 'codec': '',
               'message': 'Queued for background processing', 'created_at': time.time(), 'updated_at': time.time(),
               'cancel_requested': False, 'resume_event': threading.Event(), 'result': None, 'error': None}
        job['resume_event'].set()
        _JOBS[job_id] = job
    thread = threading.Thread(target=_run_job, args=(job, worker_data), daemon=True, name=f'hfx-{job_id[:8]}')
    thread.start()
    return job


def _run_job(job, worker_data):
    try:
        # Do not overwrite a pause/cancel action racing with thread startup.
        if job['status'] == 'queued':
            job['status'] = 'running'
        if job['kind'] == 'single':
            data, filename, algorithm = worker_data
            job['file_count'] = 1
            job['current_file'] = filename
            callback = lambda done, total, codec, state: _job_progress(job, done, total, codec, state)
            blob, stats = compress_bytes(data, filename, algorithm, progress_callback=callback, checkpoint=lambda: _job_checkpoint(job))
            _job_checkpoint(job)
            job['result'] = {'filename': filename + '.hfx', 'compressed_base64': base64.b64encode(blob).decode('ascii'), 'stats': stats}
        else:
            files, algorithm, password = worker_data
            job['file_count'] = len(files)
            buffer = io.BytesIO(); manifest = []; total_bytes = 0
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
                for index, (relative, data) in enumerate(files):
                    _job_checkpoint(job)
                    job['file_index'] = index
                    job['current_file'] = relative
                    callback = lambda done, total, codec, state, j=job: _job_progress(j, done, total, codec, state)
                    blob, stats = compress_bytes(data, relative, algorithm, progress_callback=callback, checkpoint=lambda: _job_checkpoint(job))
                    archive.writestr(relative + '.hfx', blob)
                    manifest.append({'filename': relative, 'original_bytes': len(data), 'compressed_bytes': len(blob), 'algorithm': stats['algorithm']})
                    total_bytes += len(data)
                    job['file_index'] = index + 1
                    job['progress'] = int(job['file_index'] / len(files) * 100)
                    job['updated_at'] = time.time()
                archive.writestr('HuffmanX-manifest.json', json.dumps({'format': 'HuffmanX batch v1', 'files': manifest}, indent=2))
            packed = buffer.getvalue(); filename = 'huffmanx-batch.hfxzip'
            if password:
                from cryptography.fernet import Fernet
                import os
                salt = os.urandom(16)
                key = base64.urlsafe_b64encode(hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32))
                packed = b'HFXE1' + salt + Fernet(key).encrypt(packed)
                filename = 'huffmanx-batch.hfxlock'
            job['result'] = {'archive_base64': base64.b64encode(packed).decode('ascii'), 'filename': filename,
                             'files': manifest, 'total_original_bytes': total_bytes,
                             'folder_structure_preserved': True, 'password_protected': bool(password)}
        job['status'] = 'completed'; job['progress'] = 100; job['stage'] = 'complete'; job['message'] = 'Compression completed successfully'
    except JobCancelled as exc:
        job['status'] = 'cancelled'; job['stage'] = 'cancelled'; job['message'] = str(exc)
    except Exception as exc:
        job['status'] = 'failed'; job['stage'] = 'failed'; job['error'] = str(exc); job['message'] = f'Compression failed: {exc}'
    finally:
        job['updated_at'] = time.time()


@app.post('/api/jobs/compress')
async def create_compression_job(file: UploadFile = File(...), algorithm: str = Form('auto')):
    if algorithm not in CODECS:
        raise HTTPException(400, 'Unknown algorithm')
    data = await file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise HTTPException(413, 'File exceeds 100 MB limit')
    job = _new_job('single', (data, file.filename or 'upload.bin', algorithm))
    return _public_job(job)


@app.post('/api/jobs/compress-batch')
async def create_batch_job(files: list[UploadFile] = File(...), algorithm: str = Form('auto'), password: str = Form('')):
    if algorithm not in CODECS:
        raise HTTPException(400, 'Unknown algorithm')
    if not files:
        raise HTTPException(400, 'Choose at least one file')
    if len(files) > 500:
        raise HTTPException(400, 'Maximum 500 files per batch')
    if password and len(password) < 8:
        raise HTTPException(400, 'Bundle password must be at least 8 characters')
    entries = []; total = 0; seen = set()
    for item in files:
        relative = _safe_archive_path(item.filename or 'file.bin')
        if relative in seen:
            raise HTTPException(400, f'Duplicate path in selection: {relative}')
        seen.add(relative)
        data = await item.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise HTTPException(413, f'{relative} exceeds 100 MB limit')
        total += len(data)
        if total > MAX_FILE:
            raise HTTPException(413, 'Combined batch size exceeds 100 MB limit')
        entries.append((relative, data))
    job = _new_job('batch', (entries, algorithm, password))
    return _public_job(job)


@app.get('/api/jobs/{job_id}')
def get_compression_job(job_id: str):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, 'Job not found. Jobs are cleared when the backend restarts.')
    body = _public_job(job)
    if job['status'] == 'completed':
        body['result'] = job['result']
    if job['status'] == 'failed':
        body['error'] = job['error']
    return body


@app.post('/api/jobs/{job_id}/{action}')
def control_compression_job(job_id: str, action: str):
    if action not in ('pause', 'resume', 'cancel'):
        raise HTTPException(400, 'Action must be pause, resume or cancel')
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, 'Job not found')
    if job['status'] in ('completed', 'failed', 'cancelled'):
        raise HTTPException(409, f'Job is already {job["status"]}')
    if action == 'pause':
        job['status'] = 'paused'; job['stage'] = 'paused'; job['resume_event'].clear(); job['message'] = 'Paused at a safe checkpoint'
    elif action == 'resume':
        job['resume_event'].set(); job['status'] = 'running'; job['stage'] = 'resuming'; job['message'] = 'Resuming from the next safe checkpoint'
    else:
        job['cancel_requested'] = True; job['resume_event'].set(); job['message'] = 'Cancellation requested; waiting for the active codec pass to reach a safe checkpoint'
    job['updated_at'] = time.time()
    return _public_job(job)
