# workspace.md — code-memory shared tasks (Claude Code ↔ Codex)

Đây là workspace chung, không còn là prompt dùng một lần. Claude Code được phép ghi báo cáo triển khai vào vùng CLAUDE_REPORT ở cuối file.

## Quy trình bắt buộc mỗi vòng

### Claude Code

1. Chỉ triển khai các task trong ACTIVE TASKS, trừ khi phát hiện blocker/regression mới.
2. Không tự xóa hoặc đánh dấu hoàn thành task trong ACTIVE TASKS.
3. Sau khi code và test xong, thay nội dung bên trong marker CLAUDE_REPORT bằng báo cáo mới.
4. Báo cáo phải có:
   - commit/hash và working-tree status;
   - task ID đã xử lý;
   - file/schema/API đã đổi;
   - lệnh test chính xác + kết quả;
   - smoke/integration evidence;
   - task còn thiếu, partial fix, test chưa chạy;
   - regression/task mới phát hiện.
5. Không ghi báo cáo ra ngoài marker và không xóa marker.

### Codex

1. Đọc CLAUDE_REPORT và đối chiếu trực tiếp source/diff.
2. Chạy lại test/smoke/repro quan trọng.
3. Xóa task đã đạt acceptance; task partial/fail được viết lại theo vấn đề thực tế; thêm task mới nếu phát hiện.
4. Xóa nội dung báo cáo đã review, trả CLAUDE_REPORT về placeholder cho vòng tiếp theo.

## Baseline đã được Codex xác minh

- Reviewed implementation commit: 86575f3; report commit: a52bf91.
- Full suite: 62 passed.
- python -m compileall -q codemem: pass.
- node --check web/app.js: pass.
- P0 đã xác minh và đã xóa/thu gọn: files_needing_summary trả vector_gen, canonical migration carry vector_gen vào file tombstone, gen0 retry bỏ ungated delete khi file hiện tại đã có gen>0 (nhưng còn crash-window vector_ok=0 bên dưới) và các fix vòng trước.
- Không được làm regression các phần trên.

## ACTIVE TASKS

### P0-5 — Hoàn thiện vector reconciliation lifecycle

files.vector_ok, startup/manual/switch reconcile và embed-model marker đã có. Phần còn lại:

- Reconcile chỉ thấy vector_ok=0; collection mất/corrupt bên ngoài trong khi DB còn 1 không được phát hiện.
- mark_all_vectors_stale áp dụng mọi project nhưng startup chỉ reconcile active; project khác chỉ repair khi được switch tới.
- EMBED_MODEL đổi nhưng vẫn dùng collection cố định `code`; nếu model mới khác dimension/config, mark stale rồi add vào collection cũ có thể fail vĩnh viễn. Meta lại được cập nhật trước khi rebuild thành công.
- Summary query/generation cơ bản đã sửa, nhưng summary embeddings chưa có trạng thái pending/version/reconcile.
- Re-index file xóa summary nhưng reconcile không add lại; retrieval còn bỏ qua kind `summary`, nên index này vừa không được dùng vừa có thể stale/orphan. Cần generation-aware summary state và test delete→recreate/summarize concurrency.
- Chưa có inventory/content hash để đối chiếu vector thực tế; UI chưa surface pending/repair.
- Dùng collection generation/version theo embedding model (kèm dimension/config), chỉ promote marker sau rebuild thành công; lưu content hash/inventory cho từng loại document và repair idempotent cho mọi project/summary.
- Thêm integration test collection mất/đổi model nhưng DB vẫn vector_ok=1.

### P0-6 — Serialize index/watch/delete concurrency

INDEX_LOCK đã bao stop → mutate → start cho index/select/delete. Phần còn lại:

- Generation guard không dừng callback đã copy pending và đang chờ INDEX_LOCK. Sau project delete, callback cũ có thể chạy với pid đã xóa và tạo lại file/vector mồ côi vì schema không có FK/project-exists guard.
- Summarizer vẫn ngoài lock; project bị xóa giữa job có thể để summary vector hoặc overview cho pid không còn tồn tại.
- Error mới chỉ print; chưa vào structured job log/retry.
- Re-check generation + project existence sau khi lấy INDEX_LOCK, hoặc dùng cancellable job generation; summarizer phải cùng conflict policy/job lock.
- Cần deterministic API concurrency tests cho delete/switch đúng lúc watcher đã copy pending và summarizer đang ghi.

### P0-8 — Hoàn thiện canonical-root migration rollout

roots_canon_v2, normcase dedup, overview invalidation và cleanup intent cùng transaction đã đạt. Phần còn lại:

- Có backup/rollback hoặc recovery contract rõ cho schema/data migration.
- Marker vẫn là boolean rời rạc thay vì migration version/ledger có transaction và diagnostics.
- files path-PK normal migration đã sửa, nhưng DDL `CREATE files_new` chưa có explicit BEGIN/recovery. Crash sau create trước copy để lại files_new; lần init sau CREATE lại có thể fail. Thêm recovery/ledger và test interrupted ở từng phase.
- Test upgrade thực tế từ DB chỉ có roots_canon_v1=1, transaction rollback/process interruption, overview merge, legacy vector metadata và junction thật/adapter deterministic.

### P0-10 — Mutation SQLite/vector chưa có partial-result contract

Atomic clear, SQL scope filter, forced collection fence và generation guard cho vector mới đã đạt. Các lỗi còn lại:

- Guard gen0 đã tránh xóa vector mới khi current gen>0, nhưng chỉ check generation là chưa đủ. **Codex repro crash-window:** legacy delete tạo tombstone gen0 → recreate chỉ chạy SQLite upsert gen1 rồi crash trước vector write (`vector_ok=0`) → worker ACK tombstone, `vector_delete_calls=[]`, pending tombstone=0; legacy vector vẫn có thể tồn tại.
- Chỉ ACK stale gen0 khi current row chứng minh vector generation mới đã hoàn tất (`vector_ok=1`, tốt hơn là inventory xác nhận metadata gen hiện tại). Nếu current gen>0 nhưng vector_ok=0, phải ungated-clean legacy an toàn, ACK sau success và để reconcile dựng vector mới.
- Thêm test exact cho recreate crash trước index_file và delete lần hai trước reconcile; không được mất cleanup intent hoặc để vector legacy orphan.
- DB thật Codex đọc sau commit vẫn là 29 files, **7 gen0/vector_ok=1**, marker `legacy_gen_norm` chưa tồn tại vì app thật chưa init/restart. Sau init phải mark 7 pending; cần smoke sau restart chứng minh chúng thực sự re-embed rồi gen0/missing metadata về 0 trên mọi project.
- Chroma trước vòng này có 9 vectors thiếu generation; SQLite marker không tự normalize Chroma, startup chỉ reconcile active project. Cần inventory/migration job cho tất cả project và trạng thái tiến độ.
- Summary generation query đã sửa, nhưng DB summary vẫn không có pending/version state và summarizer race với re-index/delete chưa được bảo vệ.
- Viết integration test bằng Chroma thật cho missing-field + `$lte`, delete→recreate, summary delete và canonical cleanup; fake collection chỉ xác nhận shape where, không xác nhận match/delete semantics. Codex smoke `$lte` trên collection local không hoàn tất trong >30s, cần kiểm tra timeout/performance/lock thay vì để cleanup treo INDEX_LOCK.
- `cleanup_worker` startup vẫn chỉ chạy **một lần rồi thoát**. Intent đang backoff lúc startup không tự chạy khi đến hạn; cần recurring scheduler có shutdown/cancel/backoff hoặc job system P1-16.
- Backoff chưa jitter/updated_at; UI chưa có pending/retry action.
- Acceptance: sau migration/restart không còn file/vector generation-unknown; mọi delete ack phải chứng minh target cũ đã absent và không xóa generation mới; DB/vector inventory khớp trên mọi project.

### P1-11 — Lexical retrieval và ranking

- Thay token-LIKE bằng SQLite FTS5/BM25 hoặc lexical index tương đương.
- Tokenizer hiện chỉ nhận ASCII identifier dài từ 3 ký tự, yếu với tiếng Việt và symbol ngắn.
- Pipeline: exact symbol/file/route → lexical → semantic; score threshold bằng fixture thật.
- Không dùng set iteration làm ranking nondeterministic.
- Diversity theo file/module; query unrelated phải trả insufficient evidence.

### P1-12 — Context budget token-aware

- CONTEXT_CHAR_BUDGET và MAX_HISTORY_CHARS vẫn dựa ký tự.
- Budget phải gồm system + evidence + overview + brain + history + user + output reserve.
- Test context 8192 và 32768; không nhồi đầy model nhỏ.
- Một block lớn không được break và loại mọi candidate sau.
- Sources phải liệt kê mọi file thực sự xuất hiện trong context, không chỉ file có skeleton vừa budget.

### P1-13 — Stable symbol graph + provenance

- Call graph vẫn dùng simple name; external call trùng tên internal và method cùng tên có thể bị gộp.
- Thêm stable symbol ID/qualified name, resolved/unresolved/external target, confidence và file/line provenance.
- Bổ sung import/dependency, inheritance/implements, contains và event emit/listen/producer/consumer.

### P1-14 — Mở rộng coverage codebase

- Chunk/config indexing cho README/Markdown, JSON/YAML/TOML, HTML/CSS, SQL.
- Tôn trọng .gitignore; thống kê skipped file + reason.
- Route extractors tối thiểu: FastAPI (repo hiện có 0 route), Flask/Django, NestJS/Next.js, ASP.NET controller prefix.
- Express route resolve đúng handler/middleware.
- Workflow/entrypoint/architecture/security/config facts có evidence file+line.

### P1-15 — Summary/overview validation bằng code

- Prompt chống bịa chưa đủ.
- Overview dùng basename, giới hạn 400 file và cắt 8000 ký tự âm thầm.
- Build phân cấp symbol → file → module → project.
- Lưu source hash, prompt version, model, evidence IDs và provenance.
- Reject/mark unsupported entity hoặc technology không có trong evidence.
- Summary dùng doc/body/chunks phù hợp, không chỉ skeleton.

### P1-16 — Background jobs

- Index vẫn blocking; summarize là daemon thread + progress singleton.
- Thêm job ID, project ID, phase/current file, warning/error, cancel/retry/conflict policy.
- App restart nhận biết interrupted job.
- Không cho hai job ghi cùng project.

### P1-17 — Session/project scoping

- ChatSession và active project vẫn singleton toàn server.
- Hai tab có thể switch/reset history của nhau; retrieval có thể đọc active project khác nhau giữa các bước.
- Mỗi request/session mang project_id cố định xuyên DB/vector/retrieval/chat/job.
- Tách history theo session + project; persist có giới hạn hoặc lifecycle rõ.

### P1-18 — Security boundary cho local API

- Origin/Host validation + session nonce/CSRF token cho mutation.
- Validate message/query/body length.
- Canonicalize/allowlist folder được người dùng chủ động thêm; mặc định không follow symlink ra ngoài root.
- Nếu bind ngoài localhost phải có auth rõ.
- Disable /docs mặc định khi packaged hoặc có setting.
- Không trả raw exception/path ngoài mức cần thiết.

### P1-19 — Health/lifespan/logging còn partial

/api/health cơ bản đã có nhưng chưa đủ:

- DB hiện luôn trả True sau init, chưa probe/read-write health.
- Chưa có Ollama/model/context health.
- Embedding state có thể là unknown nhưng response chỉ có embedding_failed.
- Watcher chỉ trả boolean, không root/project/generation/error.
- Dùng FastAPI lifespan để shutdown watcher/job sạch.
- Structured logs có request/job/project ID; bỏ except: pass ở critical path.
- SQLite helpers chưa dùng context manager/try-finally; Codex repro upsert OperationalError để connection mở và khóa file DB trên Windows. Mọi failure phải rollback/close deterministically.

### P1-20 — Model/context 33k chưa tự phát hiện/chọn được

- Default vẫn agent-7b-v2 + 8192.
- /api/models mới liệt kê tên, chưa đọc context capability.
- UI chưa có model/settings picker.
- Cho chọn/persist chat model, context/budget, embedding backend/model và brain.
- Cảnh báo model missing/context mismatch; không tự nhận Qwen 2B nếu model thực tế khác.

### P1-21 — Setup vẫn phụ thuộc máy tác giả

- start.bat vẫn fallback C:\Agent\Agent_Ollama\Ollama\.venv.
- Dependencies chưa lock/constraints; pytest nằm chung runtime requirements; chưa có dev extras.
- Thêm bootstrap/check Windows, Python support matrix và reproducible environment.
- Không tự tải model/embedding lớn trong startup/clear.
- Thêm .pytest_cache/ vào .gitignore và dọn cache/ACL gây Git permission warnings.

### P1-22 — README còn partial

Python và multi-project wording đã sửa. Còn:

- Roadmap vẫn đánh dấu Phase 1–3 hoàn tất dù active tasks còn nhiều.
- Tests section chưa phản ánh 62 tests và coverage multi-project/migration/vector mới.
- Bổ sung schema migration, degraded semantics, health, project lifecycle và giới hạn hiện tại.

### P2-23 — UI project/explorer

- Project sidebar/drawer: fresh/stale/indexing/error/last indexed.
- Tabs: Chat, Explorer, Routes, Workflows/Architecture, Issues/Index log.
- Source chip click mở evidence snippet + relative path/line/score/reason.
- Routes/structure filter, pagination/không truncate âm thầm.
- Hiển thị model/context thật, Ollama/embedding/watcher health và token usage.

### P2-24 — Streaming/error UX

- Kiểm tra response.ok; SSE parser hỗ trợ CRLF, nhiều data line, malformed event và final buffer.
- AbortController + Stop generation, retry/copy và loading trước token đầu.
- Poll summarize có timeout/error; hiển thị partial success.
- Thay alert bằng inline error/toast.

### P2-25 — Responsive/accessibility

- 100dvh, min-width:0, media queries 360/768/1024/1440.
- Semantic button thay example span; aria-label, keyboard navigation, :focus-visible.
- Tooltip dùng được bằng focus; prefers-reduced-motion.
- Sanitize Markdown, không bật raw HTML.
- Render-test desktop/mobile và xác nhận không horizontal overflow.

## Test gaps bắt buộc

Ngoài test riêng từng task, cần có:

1. API integration tests cho toàn bộ endpoint, đặc biệt project scoping, /api/file, /api/overview, health và mutation errors.
2. Vector nested-project delete/update isolation.
3. Watcher/summarizer/index concurrency và project switch/delete.
4. Migration schema cũ → mới + backup/rollback.
5. Realistic retrieval fixtures: Vietnamese, duplicate names, unrelated query, token budgets.
6. Route/framework + metadata chunks.
7. Security tests: origin/nonce/symlink/input limits/session isolation.
8. UI smoke: desktop/mobile, keyboard, stream abort, source drawer, job progress/error.

Lệnh kiểm tra tối thiểu:

    python -m pytest tests -q
    python -m compileall -q codemem
    node --check web/app.js

## Acceptance còn lại

- Nested projects không leak SQLite hoặc vector khi update/delete.
- Vector pending/stale được tự repair sau failure.
- Watcher/job/chat bind project ID cố định và an toàn khi concurrent operations.
- Vector/Ollama unavailable không làm lexical index/search/clear/delete crash.
- Retrieval grounded, token-aware, citation khớp evidence.
- FastAPI routes và metadata/source coverage được index.
- Model/context UI phản ánh capability thật và hỗ trợ khoảng 32–33k.
- Security/session/path tests pass.
- UI responsive, accessible, có stream abort và source explorer.
- Setup/README/migration tái tạo được.
- Không còn critical exception bị nuốt; full test suite và smoke app pass.

## CLAUDE_REPORT — temporary handoff

<!-- CLAUDE_REPORT_START -->
## Vòng: fix legacy gen0 ack crash-window (P0-10)

### Commit / working tree
- Work commit: `01a20ae` (codemem/storage/db.py, codemem/indexer/runner.py, tests/test_reconcile.py).
- Report commit: chính commit chứa thay đổi workspace.md này.
- Working tree sau report commit: clean (chỉ còn data/ gitignored). Không push.

### Task ID đã xử lý
- **P0-10** — crash-window Codex repro: guard gen0 vòng trước ack intent khi current gen>0,
  nhưng nếu recreate chỉ chạy SQLite upsert (gen1) rồi crash TRƯỚC vector write (`vector_ok=0`),
  worker ack tombstone mà không xóa → vector legacy orphan tồn tại vĩnh viễn + mất cleanup intent.

### File / schema / API đã đổi
- `codemem/storage/db.py`:
  - Đổi `file_current_gen(path, project_id) -> int|None` thành
    `file_vector_state(path, project_id) -> (vector_gen, vector_ok) | None`.
- `codemem/indexer/runner.py`:
  - `_retry_tombstones`: với file-scope intent legacy (`generation` falsy), CHỈ ack-without-delete
    khi `st = file_vector_state(...)` thỏa `st[0]>0 AND st[1]==1` (vector mới đã HOÀN TẤT →
    `index_file` đã ungated-delete vector cũ). Các trường hợp còn lại — file absent (None),
    gen 0, hoặc **gen>0 nhưng vector_ok=0 (crash-window)** — rơi xuống ungated `vectors.delete_file`
    (generation=0) rồi ack-on-success; reconcile dựng lại vector mới sau.
  - Gated intent (gen≥1) không đổi (an toàn nhờ `$lte`).
- Không đổi schema/SCHEMA_VERSION; không đổi API route.

### Lệnh test + kết quả
- `PYTHONPATH=. PYTHONUTF8=1 python -m pytest tests -q` → **64 passed** (62 baseline + 2 mới;
  1 test đổi tên/ngữ nghĩa).
- `python -m compileall -q codemem` → pass.
- `node --check web/app.js` → pass.
- Test (tests/test_reconcile.py):
  - `test_retry_legacy_gen0_stale_when_recreate_complete` — `file_vector_state`→(7,1) → ack,
    KHÔNG gọi `vectors.delete_file`.
  - `test_retry_legacy_gen0_cleans_when_recreate_incomplete` (**crash-window**) —
    `file_vector_state`→(1,0) → ungated `delete_file(generation=0)` + ack sau success (KHÔNG mất
    intent, KHÔNG để orphan).
  - `test_retry_legacy_gen0_deletes_when_file_absent` — `file_vector_state`→None → ungated delete.
  - `test_file_vector_state_reflects_db` — DB thật: chưa có→None; sau upsert→(g,0); sau
    set_vector_ok(True)→(g,1).

### Smoke / integration evidence
- Không chạy smoke DB thật vòng này (chỉ đổi logic guard + helper SQL, không đổi schema/migration;
  64/64 test xanh gồm 1 test DB thật cho `file_vector_state`). Real-DB migration đã smoke ở 2 vòng
  trước và không đổi.

### Partial / còn thiếu (KHÔNG hoàn thành vòng này — vẫn mở trong ACTIVE TASKS)
- **P0-10 — integration test bằng Chroma THẬT** (missing-field + `$lte`, delete→recreate, summary
  delete, canonical cleanup) VẪN dùng fake/monkeypatch. Crash-window cũng test bằng monkeypatch
  `file_vector_state`/`delete_file`, chưa chứng minh semantics xóa thật trên Chroma. Codex smoke
  `$lte` >30s chưa điều tra (performance/lock).
- **P0-10 — recurring cleanup scheduler** (`cleanup_worker` one-shot; backoff không tự đến hạn) —
  chưa làm (gắn P1-16).
- **P0-10 — normalize 9 vector thật thiếu generation trong Chroma + smoke sau restart** chứng minh
  re-embed về gen>0 trên MỌI project — chưa; startup chỉ reconcile active project.
- **P0-10 — backoff jitter/updated_at; UI pending/retry** — chưa.
- **P0-5 — summary pending/version/reconcile state; retrieval kind `summary`; re-index xóa summary
  nhưng reconcile không add lại; collection generation theo embed-model/dimension** — chưa.
- **P0-8 — files_new DDL recovery/ledger + migration version/ledger + backup/rollback** — chưa.
- **P0-6 — re-check generation/project-existence sau INDEX_LOCK; summarizer trong lock** — chưa.

### Regression / phát hiện mới
- Không phát hiện regression mới. 64/64 xanh; các P0 baseline vẫn pass.
- Lưu ý reviewer: guard vẫn dựa giả định "vector_ok=1 ⇒ index_file đã ungated-delete vector cũ
  trước khi add". Đúng với mọi đường ghi hiện tại (`_index_one`, `reconcile_vectors` đều qua
  `vectors.index_file`, mà `index_file` mở đầu bằng `delete_file(path, project_id)` ungated).
  `set_vector_ok(True)` chỉ được gọi sau khi `index_file` trả True (xem `_index_one`/`reconcile_vectors`),
  nên vector_ok=1 thực sự hàm ý add đã chạy. Nếu sau này có đường set vector_ok=1 mà không qua
  index_file thì giả định cần xét lại.
<!-- CLAUDE_REPORT_END -->
