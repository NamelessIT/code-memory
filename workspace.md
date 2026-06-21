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

- Reviewed implementation commit: aced57c; report commit: 9572e7d.
- Full suite: 55 passed.
- python -m compileall -q codemem: pass.
- node --check web/app.js: pass.
- P0 đã xác minh và đã xóa/thu gọn: crash-safe vector_ok/vector_gen cho upsert mới, atomic clear outbox, scope filter trước LIMIT, collection fence mọi pending intent, generation guard cho vector mới có metadata, tombstone-v1 interrupted recovery và các fix vòng trước.
- Không được làm regression các phần trên.

## ACTIVE TASKS

### P0-5 — Hoàn thiện vector reconciliation lifecycle

files.vector_ok, startup/manual/switch reconcile và embed-model marker đã có. Phần còn lại:

- Reconcile chỉ thấy vector_ok=0; collection mất/corrupt bên ngoài trong khi DB còn 1 không được phát hiện.
- mark_all_vectors_stale áp dụng mọi project nhưng startup chỉ reconcile active; project khác chỉ repair khi được switch tới.
- EMBED_MODEL đổi nhưng vẫn dùng collection cố định `code`; nếu model mới khác dimension/config, mark stale rồi add vào collection cũ có thể fail vĩnh viễn. Meta lại được cập nhật trước khi rebuild thành công.
- Summary embeddings chưa có trạng thái pending/version/reconcile và `index_summary` chưa ghi generation. File tombstone delete theo `$lte generation` không match summary thiếu field; re-index file lại xóa summary nhưng reconcile không add lại. Retrieval hiện còn bỏ qua kind `summary`, nên index này vừa không được dùng vừa có thể orphan.
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
- **Codex repro path-global legacy:** migration thêm vector_gen vào bảng files cũ rồi `files_new` lại không khai báo/copy cột này. Sau init_db, `PRAGMA files` không có vector_gen và upsert_file lỗi `OperationalError: table files has no column named vector_gen`.
- Sửa files_new gồm vector_gen/vector_ok và chạy post-migration schema assertion; test DB files path-primary-key thật cũ rồi index/upsert thành công.
- Canonical migration tạo file tombstone generation mặc định 0 trong khi vector legacy thiếu metadata generation; cleanup có thể ack mà không xóa orphan. Migration phải có chiến lược normalize legacy vector trước khi guard generation.
- Test upgrade thực tế từ DB chỉ có roots_canon_v1=1, transaction rollback/process interruption, overview merge, legacy vector metadata và junction thật/adapter deterministic.

### P0-10 — Mutation SQLite/vector chưa có partial-result contract

Atomic clear, SQL scope filter, forced collection fence và generation guard cho vector mới đã đạt. Các lỗi còn lại:

- **Legacy delete không an toàn:** generation=0 tombstone dùng Chroma where `generation <= 0`, nhưng metadata không có field generation sẽ không match. Caller coi delete không lỗi là thành công rồi ack intent, để orphan vĩnh viễn.
- DB thực tế Codex đọc được: 29 files, **7 files vector_gen=0 nhưng vector_ok=1**; Chroma có 269 vectors, **9 vectors thiếu generation**. Phải migrate/mark pending và normalize, không chỉ ghi chú “reindex sau”.
- Summary vectors thiếu generation cũng rơi vào cùng lỗi delete/orphan. Gắn generation cho mọi document kind hoặc tách cleanup có inventory/ID generation rõ.
- Viết integration test bằng Chroma thật cho missing-field + `$lte`, delete→recreate, summary delete và canonical cleanup; fake collection chỉ xác nhận shape where, không xác nhận match/delete semantics. Codex smoke `$lte` trên collection local không hoàn tất trong >30s, cần kiểm tra timeout/performance/lock thay vì để cleanup treo INDEX_LOCK.
- `cleanup_worker` startup vẫn chỉ chạy **một lần rồi thoát**. Intent đang backoff lúc startup không tự chạy khi đến hạn; cần recurring scheduler có shutdown/cancel/backoff hoặc job system P1-16.
- Backoff chưa jitter/updated_at; UI chưa có pending/retry action.
- Acceptance: sau migration không còn file/vector generation-unknown; mọi delete ack phải chứng minh target cũ đã absent và không xóa generation mới; DB/vector inventory khớp sau restart.

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
- Tests section chưa phản ánh 55 tests và coverage multi-project/migration/vector mới.
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
## Vòng: fix regression files_new drop vector_gen + normalize legacy vector

### Commit / working tree
- Work commit: `86698c7` (codemem/ + tests/).
- Report commit: chính commit chứa thay đổi workspace.md này.
- Working tree sau report commit: clean (chỉ còn data/ gitignored). Không push.

### Task ID đã xử lý
- **P0-8** — Codex repro path-global legacy (CRITICAL regression do tôi gây vòng trước).
- **P0-10** — legacy delete không an toàn (generation=0 + vector thiếu field generation).
- **P0-5** — `index_summary` chưa ghi generation.

### File / schema / API đã đổi
- `codemem/storage/db.py`:
  - **`files_new` recreate** (nhánh migrate path-PK → composite) giờ KHAI BÁO và COPY
    `vector_ok INTEGER DEFAULT 1, vector_gen INTEGER DEFAULT 0` (dùng `COALESCE(...,1)/(...,0)`),
    thực thi qua `conn.execute` atomic. Đây là fix gốc lỗi `OperationalError: table files
    has no column named vector_gen`.
  - **Post-migration schema repair**: sau migrate, `PRAGMA table_info(files)`; nếu thiếu
    `vector_gen`/`vector_ok` thì `ALTER TABLE ADD COLUMN` (idempotent self-heal).
  - **Marker `legacy_gen_norm`**: nếu chưa set → `UPDATE files SET vector_ok=0 WHERE
    COALESCE(vector_gen,0)=0` (mark legacy file pending để reconcile re-embed ở generation
    thật), rồi set marker = '1'. Chạy 1 lần, trước commit cuối của init_db.
  - SCHEMA_VERSION không đổi (vẫn "3"); thêm meta key `legacy_gen_norm`.
- `codemem/storage/vectors.py`:
  - `delete_file(path, project_id, generation)`: đổi gate sang `if generation:` (truthy).
    gen ≥ 1 → thêm `{"generation": {"$lte": generation}}`. gen 0/None (vector legacy KHÔNG
    có field generation) → KHÔNG gate → xóa hết → tránh orphan-but-acked.
  - `index_summary(..., generation=0)`: thêm tham số + ghi `generation` vào metadata summary.
- `codemem/indexer/summarizer.py`:
  - `run_summarize` truyền `generation=f.get("vector_gen", 0)` vào `index_summary`.
- Không đổi API route nào.

### Lệnh test + kết quả
- `PYTHONPATH=. PYTHONUTF8=1 python -m pytest tests -q` → **58 passed** (55 baseline + 3 mới).
- `python -m compileall -q codemem` → pass.
- `node --check web/app.js` → pass.
- Test mới:
  - `tests/test_tombstones.py::test_legacy_pathpk_db_migrates_then_upsert_works` — tạo DB
    `files` path-PK cũ (không có id/vector_gen) → `init_db()` → assert files có `id`+`vector_gen`,
    rồi `upsert_file` thành công (gen≥1), KHÔNG OperationalError. (repro chính xác của Codex)
  - `tests/test_tombstones.py::test_legacy_gen_norm_marks_pending` — file vector_gen=0/vector_ok=1
    + xóa marker → `init_db` rerun normalize → `files_pending_vector` = 1.
  - `tests/test_vectors_degraded.py::test_delete_file_generation_zero_no_gate` — gen=0 →
    where chỉ có file_path+project_id, KHÔNG có điều kiện generation.

### Smoke / integration evidence (trên BẢN COPY của data/code_index.db thật, non-destructive)
- BEFORE: files cols đầy đủ (đã ở v3), 28 files, schema_version=3.
- Sau `init_db()` (idempotent): 28 files giữ nguyên, schema_version=3, `legacy_gen_norm=1`,
  **7 files vector_ok=0** (đúng 7 file legacy vector_gen=0 mà Codex báo), tombstones pending=0.
- Smoke upsert/delete trên copy: `upsert_file` → gen=40 OK; `delete_file` → 1 due tombstone OK.
- Bản copy đã xóa sau test; DB thật không bị chạm.

### Partial / còn thiếu (KHÔNG hoàn thành vòng này — vẫn mở trong ACTIVE TASKS)
- **P0-10 — 9 vectors thật thiếu generation chưa được normalize trong Chroma**: tôi chỉ
  normalize phía SQLite (mark file pending) + làm delete legacy an toàn (gen 0 không gate).
  Việc backfill/re-embed thực tế phụ thuộc reconcile chạy và Ollama/embedding online — chưa
  chứng minh inventory Chroma sau restart khớp DB. Cần integration test bằng Chroma THẬT cho
  missing-field + `$lte`, delete→recreate, summary delete (fake collection chỉ verify shape).
- **P0-10 — Codex smoke `$lte` trên collection local >30s chưa hoàn tất**: chưa điều tra
  performance/timeout/lock; rủi ro cleanup treo INDEX_LOCK vẫn còn.
- **P0-10 — `cleanup_worker` startup vẫn one-shot**: chưa có recurring scheduler/backoff
  resume (gắn với P1-16). Chưa làm.
- **P0-5 — summary embeddings**: đã ghi generation, NHƯNG retrieval vẫn bỏ qua kind `summary`
  (vừa không dùng vừa có thể orphan); chưa có pending/version/reconcile cho summary; collection
  generation theo embedding-model/dimension chưa làm. Chưa có integration test "collection mất/đổi
  model nhưng DB vẫn vector_ok=1".
- **P0-8 — migration version/ledger + backup/rollback** chưa làm; marker vẫn là boolean rời rạc.
  Test rollback/process-interruption (ngoài _v1 recovery đã có) và junction thật chưa thêm.

### Regression / phát hiện mới
- Không phát hiện regression mới so với baseline đã Codex xác minh. Suite 58/58 xanh, các P0
  baseline (atomic clear, scope filter, collection fence, generation guard cho vector mới,
  tombstone-v1 recovery) vẫn pass.
- Lưu ý: schema repair + legacy_gen_norm chạy mỗi `init_db` nhưng được guard bằng PRAGMA-check
  và marker nên idempotent (đã xác minh init_db lần 2 trên copy không đổi dữ liệu).
<!-- CLAUDE_REPORT_END -->
