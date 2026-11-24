# HuffmanX v3.0 — Verification Report

**Verification date:** 24 November 2026  
**Project version:** 3.0.0

## Automated checks

| Check | Result |
|---|---:|
| Python automated test suite (`python -m pytest -q`) | **84 passed** |
| Python compilation (`python -m compileall -q backend`) | Passed |
| JavaScript syntax (`node --check frontend/app.js`) | Passed |
| LZ77 round-trip stress cases (random, repeated, mixed) | Passed |
| Single-file background job round trip | Passed |
| Encrypted batch folder round trip | Passed |
| SHA-256 / byte identity checks | Passed |
| Job pause/resume/cancel checkpoints and startup race | Passed |
| Batch path traversal and duplicate-path rejection | Passed |

## Chromium UI smoke test

The frontend was exercised using headless Chromium against the running FastAPI service. The UI test covered:

- Backend-online indicator, file selection, Smart Analyzer and preview.
- Single-file background compression and output metrics.
- Huffman DSA visualizer and step-by-step decode.
- Algorithm size comparison and speed/memory benchmark.
- Original/restored byte-integrity comparison.
- Batch job creation, duplicate-content filtering and bundle download.
- Multiple-folder relative-path collection (two separate folder-entry test fixtures).
- Storage calculator.
- Mobile viewport at 390 px: document width remained 390 px with no horizontal overflow.
- No JavaScript console or page errors were reported in the exercised flow.

**Test-environment note:** direct browser navigation to local HTTP/file URLs was blocked by the container's browser policy. The UI was therefore loaded as an in-memory document with the same project HTML, CSS and JavaScript; a small in-memory `localStorage` shim was used because the sandbox's opaque document origin denies browser localStorage access. The FastAPI calls still reached the real local backend. Persistent browser storage and a physical Windows/Edge session were not tested in this container.

## Known operational limits

- Jobs are in-memory and disappear when the backend process restarts.
- Pause/cancel act at safe checkpoints between codec passes and files; an active codec call is allowed to finish rather than being forcibly interrupted mid-operation.
- The batch workload is limited to 500 files and 100 MB combined; each individual input is limited to 100 MB.
- Analytics/history live in the browser profile's localStorage, not in a server database.
- This is a local project/demo application, not a hardened public multi-user production service.
- Compression size reduction is never guaranteed for already-compressed or tiny files; exact byte restoration and integrity checks are the priority.
