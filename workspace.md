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

- Reviewed implementation commit: ada1dbd; report commit: e59836f.
- Full suite: 69 passed.
- python -m compileall -q codemem: pass.
- node --check web/app.js: pass.
- P0 đã xác minh và đã xóa/thu gọn: reconcile-all duyệt mọi project; legacy gen0 được cấp generation thật và chỉ set `vector_ok=1` nếu generation còn khớp; scheduler cleanup chạy lặp, giữ reference khi stop timeout và không tạo duplicate worker; shutdown hook cơ bản và các fix vòng trước.
- Không được làm regression các phần trên.

## ACTIVE TASKS

### P0-5 — Hoàn thiện vector reconciliation lifecycle

files.vector_ok, startup/manual/switch reconcile và embed-model marker đã có. Phần còn lại:

- Reconcile chỉ thấy vector_ok=0; collection mất/corrupt bên ngoài trong khi DB còn 1 không được phát hiện.
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

- `upsert_file()` và `reserve_file_generation()` chỉ lấy `meta.vec_gen_seq + 1`, không đối chiếu `MAX(files.vector_gen)` hoặc `MAX(vector_tombstones.generation)`. Sau restore/import/migration làm mất hoặc làm stale meta, generation mới có thể tụt (ví dụ file/tombstone cũ gen 50–100 nhưng lần ghi mới nhận gen 1); tombstone cũ với điều kiện `$lte` khi đó có thể xóa nhầm vector mới. Phải reserve atomically từ `max(meta sequence, max file generation, max tombstone generation) + 1`, repair invariant trong migration/startup, và thêm regression test DB có high generation nhưng meta thiếu/thấp.
- Chroma trước vòng này có 9 vectors thiếu generation; SQLite marker không tự normalize Chroma. Startup đã reconcile mọi project nhưng chưa có inventory/migration job đối chiếu DB↔Chroma và trạng thái tiến độ.
- Summary generation query đã sửa, nhưng DB summary vẫn không có pending/version state và summarizer race với re-index/delete chưa được bảo vệ.
- Viết integration test bằng Chroma thật cho missing-field + `$lte`, delete→recreate, summary delete và canonical cleanup; fake collection chỉ xác nhận shape where, không xác nhận match/delete semantics. Codex smoke `$lte` trên collection local không hoàn tất trong >30s, cần kiểm tra timeout/performance/lock thay vì để cleanup treo INDEX_LOCK.
- Scheduler recurring đã giữ reference khi stop timeout, không tạo duplicate và health đã expose thread còn sống; tuy nhiên health chưa phân biệt healthy/running với stuck.
- Chroma operation hiện không có timeout/cancel và từng treo >30s trong smoke; Event chỉ dừng giữa các vòng, không dừng call đang giữ INDEX_LOCK. Cần bounded timeout/process isolation hoặc cooperative cancellation trước khi tuyên bố shutdown sạch.
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
- Tests section chưa phản ánh 69 tests và coverage multi-project/migration/vector mới.
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
## Vòng: monotonic generation allocator + scheduler stuck-state (P0-10)

### Commit / working tree
- Work commit: `d26eeae` (db.py, runner.py, server.py, tests/test_tombstones.py, tests/test_reconcile.py).
- Report commit: chính commit chứa thay đổi workspace.md này.
- Working tree sau report commit: clean (chỉ còn data/ gitignored). Không push.

### Task ID đã xử lý
- **P0-10 (headline)** — Codex repro: `upsert_file()`/`reserve_file_generation()` chỉ lấy
  `meta.vec_gen_seq + 1`, không đối chiếu `MAX(files.vector_gen)`/`MAX(vector_tombstones.generation)`.
  Sau restore/import làm mất/stale meta, gen mới có thể tụt (file cũ gen 90 nhưng ghi mới nhận gen 1)
  → tombstone `$lte` cũ xóa nhầm vector mới.
- **P0-10** — health chưa phân biệt healthy/running với stuck.

### File / schema / API đã đổi
- `codemem/storage/db.py`:
  - **`_next_generation(conn)`**: cấp generation MONOTONIC =
    `max(meta.vec_gen_seq, MAX(files.vector_gen), MAX(vector_tombstones.generation)) + 1`, ghi lại
    meta; chạy trong transaction của caller (dùng conn truyền vào). `upsert_file` và
    `reserve_file_generation` đều dùng hàm này (thay vì `meta+1` thuần).
  - `init_db`: thêm bước repair invariant `meta.vec_gen_seq >= max(file gen, tombstone gen)` lúc
    startup/migration (chống tụt gen sau restore/import).
- `codemem/indexer/runner.py`:
  - Scheduler: thêm heartbeat `_cleanup_beat` (`time.monotonic()`) + `_cleanup_busy` quanh
    `cleanup_worker`. **`cleanup_scheduler_status(stuck_after=120)`** trả
    `{running, busy, stuck, busy_age}`; `stuck = thread sống AND busy AND busy_age >= stuck_after`.
    Giữ `cleanup_scheduler_running()`.
- `codemem/api/server.py`:
  - `/api/health` field `cleanup_scheduler` đổi từ boolean → dict `cleanup_scheduler_status()`
    (running/busy/stuck/busy_age).
- Không đổi schema/SCHEMA_VERSION; không thêm/đổi route (vẫn 26).

### Lệnh test + kết quả
- `PYTHONPATH=. PYTHONUTF8=1 python -m pytest tests -q` → **72 passed** (69 baseline + 3 mới).
- `python -m compileall -q codemem` → pass.
- `node --check web/app.js` → pass.
- Test mới:
  - `tests/test_tombstones.py::test_generation_monotonic_after_stale_meta` — file gen 90 + tombstone
    gen 75 + meta vec_gen_seq bị xóa → `upsert_file` trả gen > 90; `reserve_file_generation` > gen đó.
  - `tests/test_tombstones.py::test_init_repairs_generation_invariant` — file gen 120 + meta='3' (stale)
    → sau `init_db`, `vec_gen_seq >= 120`.
  - `tests/test_reconcile.py::test_cleanup_scheduler_status_detects_stuck` — worker block:
    `status(stuck_after=0)` → running/busy/stuck=True; `status(stuck_after=120)` → stuck=False; sau
    release+stop → running=False.

### Smoke / integration evidence (BẢN COPY data/code_index.db thật, non-destructive)
- `init_db` trên copy: `vec_gen_seq=95`, `MAX(file gen)=93`, `MAX(tomb gen)=0` → invariant đã đúng.
- Giả lập restore staleify meta (`vec_gen_seq='2'`) + re-init → repair về `93` (>= max file gen).
- `upsert_file` sau đó → gen `94` (> MAX file gen 93) → monotonic xác nhận trên dữ liệu thật.
- Bản copy đã xóa; DB thật không bị chạm.

### Partial / còn thiếu (KHÔNG hoàn thành vòng này — vẫn mở trong ACTIVE TASKS)
- **P0-10 — bounded timeout/cancel cho call Chroma đang treo**: status mới chỉ PHÁT HIỆN stuck
  (health), Event vẫn chỉ dừng giữa các vòng; call Chroma đang giữ INDEX_LOCK vẫn phải chạy xong.
  Cooperative cancellation / process isolation CHƯA.
- **P0-10 — inventory/migration job đối chiếu DB↔Chroma cho mọi project + progress state**: CHƯA.
- **P0-10 — integration test bằng Chroma THẬT** (missing-field + `$lte`, delete→recreate, summary
  delete) + điều tra `$lte` >30s: CHƯA (vẫn fake/monkeypatch).
- **P0-10 — smoke restart với Ollama LIVE** ghi metadata gen vào Chroma thật (9 vector thiếu
  generation): CHƯA (smoke vẫn stub vector write).
- **P0-10 — backoff jitter/updated_at; UI pending/retry**: CHƯA.
- **P0-5 — summary pending/version/reconcile state; retrieval kind `summary`; reconcile add lại
  summary; collection generation theo embed-model/dimension**: CHƯA.
- **P0-8 — files_new DDL recovery/ledger; migration version/ledger + backup/rollback**: CHƯA.
- **P0-6 — re-check generation/project-existence sau INDEX_LOCK; summarizer trong lock**: CHƯA.
- **P1-19 — FastAPI lifespan** (hiện `@app.on_event`): CHƯA.

### Regression / phát hiện mới
- Không phát hiện regression mới. 72/72 xanh.
- Lưu ý reviewer: `_next_generation` đọc-MAX-rồi-ghi trong cùng `conn` của caller; an toàn nhờ
  INDEX_LOCK serialize ghi ở mức app + MAX-based nên đúng cả khi meta lệch. `stuck` dùng
  `busy_age >= stuck_after` (không phải `>`) vì `time.monotonic()` trên máy này phân giải ~1ms, đọc
  ngay sau heartbeat có thể cho age 0.0; ngưỡng mặc định health là 120s nên không ảnh hưởng thực tế.
<!-- CLAUDE_REPORT_END -->
