# HuffmanX v3.0 — Universal File Compression & DSA Lab

HuffmanX is a local-first, file-agnostic compression application built with **Python FastAPI + HTML/CSS/JavaScript**. It compresses raw bytes, writes a custom `.hfx` stream, and verifies the restored bytes using SHA-256. Folder bundles use a ZIP container (`.hfxzip`) containing the individual `.hfx` files and a manifest.

## v3.0 features

### Compression engine
- Huffman, RLE, LZ77, LZW and DEFLATE (zlib).
- Auto mode executes all five encoders and selects the smallest complete HFX container for that input.
- Optimized bounded-candidate LZ77 search to avoid an unbounded quadratic scan.
- Single-file and batch/folder processing, with original relative paths preserved.
- Drop multiple folders/files together in Chromium-based browsers (Chrome / Edge). The standard folder picker also supports a selected directory.
- Optional password-protected folder bundles using scrypt key derivation and Fernet authenticated encryption. Passwords must be at least 8 characters; there is no recovery mechanism.
- Background job endpoints with progress, pause, resume and cancel controls. Pause/cancel are cooperative: they take effect at safe checkpoints between codec passes and between files, not by forcibly interrupting a Python codec in the middle of a CPU operation.
- File and batch limits: 100 MB per file, 100 MB combined batch, up to 500 batch files.

### DSA and algorithm learning
- Byte-frequency table, Huffman tree, merge sequence and min-heap playback.
- Step-through and animated sample encoding and decoding.
- Algorithm Lab compares actual HFX output sizes for Huffman, RLE, LZ77, LZW and DEFLATE.
- Smart Analyzer measures all supported outputs, reports sample entropy and recommends the smallest measured container.
- Benchmark reports elapsed time and Python-traced peak allocation for each algorithm.

### Professional workflow and analytics
- SHA-256 integrity verification during single-file and batch restoration.
- Original-vs-restored byte identity and digest comparison.
- Text preview (UTF-8, up to 2 MB) and short binary hex preview.
- Client-side SHA-256 duplicate detection when selecting a batch; duplicate-content files are skipped in the UI.
- Download history, compression history, aggregate size analytics, activity chart, file-extension and algorithm breakdowns, plus a storage-savings calculator are stored in browser localStorage. File contents are not saved in the history.
- Dark/light theme, responsive layout, motion preferences, glass-like panels and restrained 3D card tilt/cursor interactions.

## Important compression note
Already-compressed or encrypted formats (for example MP4, JPG, MP3, ZIP, 7z and many PDFs) may not shrink. HuffmanX always restores the original bytes; it does not promise a size reduction. A negative “saved” percentage means the HFX container became larger than the input.

## Requirements
- Python 3.10 or later.
- A current Chrome, Edge, Firefox or Safari browser. Multi-folder drag-and-drop relies on the Chromium `webkitGetAsEntry` API; the folder picker remains available elsewhere.
- Dependencies are listed in `requirements.txt`, including `cryptography` for encrypted bundles.

## Run on Windows (VS Code)

1. Extract the ZIP and open the `Huffman-Data-Compression` folder in VS Code.
2. Open a PowerShell terminal at the project root and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

3. Start the backend in terminal 1:

```powershell
cd backend
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

4. Start the frontend in terminal 2:

```powershell
cd frontend
python -m http.server 5500 --bind 127.0.0.1
```

5. Open **http://127.0.0.1:5500**. API documentation is at **http://127.0.0.1:8000/docs**. Keep both terminal processes running.

You can also run `start_windows.bat` from the project root; it creates the virtual environment if needed, installs dependencies and opens separate backend/frontend terminals.

## Run tests

From the project root with the virtual environment active:

```powershell
python -m pytest -q
python -m compileall -q backend
node --check frontend/app.js
```

The test suite covers codec round trips, corrupt streams, LZ77 stress data, API compression/restore, batch folder hierarchy and path validation, password-protected bundles, analysis/preview, benchmark output, integrity comparison, background single/batch jobs, job pause/resume/cancel checkpoints and the DSA encode/decode data.

## Job behaviour and limits
- Background jobs run in the FastAPI process and are kept in memory. Restarting the backend clears its job list; this is not a distributed task queue or durable job database.
- Progress and controls are cooperative at safe checkpoints. A currently-running codec pass is allowed to finish before pause/cancel is acted on.
- Analytics/history are browser-local, tied to that browser profile, and can be exported as JSON from Settings.
- Files are held in memory while processing. This is designed for a local college-project/demo workload, not an internet-facing multi-user production service.
- `.hfx` is HuffmanX-specific, while `.hfxzip` is a ZIP package containing `.hfx` streams and a manifest. It is not a replacement for general-purpose ZIP software.

## Main API endpoints
- `GET /api/health`
- `POST /api/compress`, `POST /api/decompress`
- `POST /api/compress-batch`, `POST /api/decompress-batch`
- `POST /api/analyze`, `POST /api/preview`, `POST /api/visualize`
- `POST /api/compare`, `POST /api/benchmark`, `POST /api/integrity/compare`
- `POST /api/jobs/compress`, `POST /api/jobs/compress-batch`
- `GET /api/jobs/{job_id}`, `POST /api/jobs/{job_id}/pause|resume|cancel`
