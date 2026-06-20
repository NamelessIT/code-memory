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

- Reviewed implementation commit: 5feef23; report commit: 1841877.
- Full suite: 45 passed.
- python -m compileall -q codemem: pass.
- node --check web/app.js: pass.
- P0 đã xác minh và đã xóa/thu gọn: typed absent-vs-error vector delete, project existence check trong INDEX_LOCK, clear stop-in-lock, roots_canon_v2 + overview invalidation, migration ghi cleanup intent thay vì gọi Chroma trong transaction, tombstone dedup/backoff/fair batching/health cơ bản và các fix vòng trước.
- Không được làm regression các phần trên.

## ACTIVE TASKS

### P0-5 — Hoàn thiện vector reconciliation lifecycle

files.vector_ok, startup/manual/switch reconcile và embed-model marker đã có. Phần còn lại:

- Reconcile chỉ thấy vector_ok=0; collection mất/corrupt bên ngoài trong khi DB còn 1 không được phát hiện.
- mark_all_vectors_stale áp dụng mọi project nhưng startup chỉ reconcile active; project khác chỉ repair khi được switch tới.
- EMBED_MODEL đổi nhưng vẫn dùng collection cố định `code`; nếu model mới khác dimension/config, mark stale rồi add vào collection cũ có thể fail vĩnh viễn. Meta lại được cập nhật trước khi rebuild thành công.
- Summary embeddings chưa có trạng thái pending/version/reconcile. Re-index file xóa cả summary vector qua delete_file nhưng reconcile chỉ add lại file/symbol vectors, nên summary vector có thể biến mất sau model-change repair.
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
- Test upgrade thực tế từ DB chỉ có roots_canon_v1=1, transaction rollback/process interruption, overview merge và junction thật/adapter deterministic.

### P0-10 — Mutation SQLite/vector chưa có partial-result contract

Typed absent/error, scope file/project/collection, dedup, backoff, fair batching, clear-wipe và health stats đã đạt. Các lỗi còn lại:

- **Schema upgrade làm mất intent:** init_db thấy bảng tombstone v1 thì DROP rồi CREATE, không copy row. Codex repro DB cũ có 1 pending → sau upgrade còn 0. Phải migrate bằng rename/create/`INSERT OR IGNORE SELECT COALESCE(...)`/drop trong transaction và test bảo toàn row.
- **Chưa phải transactional outbox:** delete_file, delete_project và clear commit SQLite trước; chỉ add tombstone sau khi vector trả False. Process kill/exception giữa hai bước vẫn tạo orphan không có intent. Luôn ghi intent trong cùng transaction với SQLite mutation, commit, thực hiện vector delete, rồi ack/xóa intent khi thành công.
- **Intent cũ có thể xóa vector mới:** tombstone chỉ định danh `(scope,pid,path)`, không có generation/content hash. File được tạo lại trong lúc backoff vẫn có thể bị retry cũ xóa; Codex repro cho thấy delete thành công nhưng DB vẫn `vector_ok=1`, `pending_repair=0`.
- Collection tombstone có thể được retry ở cuối index_project (qua reconcile) và xóa collection vừa index; các file mới vẫn vector_ok=1. Cleanup collection phải chạy/fence trước mọi vector write hoặc đổi generation rồi mark/rebuild nhất quán.
- Retry không có liveness độc lập: sau clear hoặc xóa project cuối, không còn active pid nên `/api/reconcile` trả 400 và startup không chạy reconcile; intent có thể nằm vĩnh viễn đến lần index sau. Thêm startup/background cleanup worker hoặc endpoint không phụ thuộc project.
- `last_error` hiện luôn là chuỗi chung `vector delete failed`, không lưu nguyên nhân thực; chưa có updated_at/jitter/structured diagnostics.
- Thêm test crash-window/outbox, migration v1 giữ row, delete→recreate-before-retry, clear-fail→index-new-project, last-project delete/restart và retry không active project; surface retry/action trong UI/job.

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
- Tests section chưa phản ánh 40 tests và coverage multi-project/migration/vector mới.
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
## Vòng — P0-10 transactional outbox (kèm schema-preserve, project-independent worker, fence)

**Commit:** work `5599a9e` (report commit ngay sau). **Working tree:** clean sau report.
**Env:** Python 3.12.13 (venv Ollama), chromadb 1.5.9, watchdog 6.0.0.

### Task đã xử lý (P0-10)
- **Schema upgrade GIỮ row (repro 1→1):** v1→v2 không DROP mất dữ liệu nữa — `ALTER RENAME` → `CREATE` v2 → `INSERT OR IGNORE SELECT COALESCE(...)` → `DROP` bảng cũ. Test bảo toàn row.
- **Transactional outbox:** `db.delete_file`/`db.delete_project` ghi cleanup intent **trong cùng transaction SQLite** với việc xoá row; caller gọi `vectors.delete_*` rồi `db.ack_tombstone(...)` khi thành công. Crash/exception giữa 2 bước → intent đã durable → worker dọn sau (hết orphan-không-intent). `/api/clear`: `add_tombstone("collection")` **trước** `vectors.clear_all()`, ack khi ok.
- **Project-independent cleanup:** `runner.cleanup_worker()` retry mọi scope không cần active project; `/api/cleanup/retry` endpoint + chạy ở **startup background** → intent được dọn kể cả sau khi clear/xoá hết project (trước đây `/api/reconcile` trả 400, intent kẹt vĩnh viễn).
- **Collection fence:** `index_project` xử lý collection intent **trước** khi ghi vector; reconcile sau index dùng `include_collection=False` → không wipe collection vừa index. Test `scopes` filter.
- **last_error thật:** `vectors.last_error()` (get_collection/delete/clear lưu message) → `record_tombstone_failure(id, err)` thay vì chuỗi chung.

### File/API đã đổi
- `codemem/storage/db.py`: schema v1→v2 preserve; `delete_file`/`delete_project` ghi intent atomic; `ack_tombstone`.
- `codemem/storage/vectors.py`: `last_error()` + set `_last_error` ở delete/clear failures.
- `codemem/indexer/runner.py`: `_retry_tombstones(scopes=)`, `cleanup_worker()`, `reconcile_vectors(include_collection=)`, index fence + ack outbox.
- `codemem/api/server.py`: `/api/cleanup/retry`; `/api/clear` outbox; delete ack; startup cleanup worker.

### Test + kết quả
- `python -m pytest tests -q` → **49 passed** (mới: schema-v1-preserve, outbox delete_file/project intent+ack, cleanup_worker independent, scopes-filter fence, collapse-then-project-intent, real last_error). `compileall` + `node --check` pass; **26 routes**.
- Live smoke: `/api/health` → `cleanup:{pending,failed,last_error}`; `/api/cleanup/retry` → 200 `{cleared, cleanup}`. Real DB intact 27 file / vector_pending 0.

### Partial / chưa làm
- **P0-10 còn lại — generation/content-hash trên intent:** tombstone vẫn chỉ `(scope,pid,path)`, **chưa có generation/hash** → file được re-index trong lúc backoff vẫn có thể bị intent cũ xoá vector mới (Codex repro delete-success-nhưng-vector_ok=1 chưa fix). Cần gắn generation/hash vào intent + so khớp trước khi xoá. Backoff chưa có jitter; chưa surface retry/action trong **UI**.
- **P0-8**: vẫn marker boolean (`roots_canon_v2`) — chưa migration-version/ledger + backup/rollback; chưa test junction thật + process-interruption giữa transform và retry.
- **P0-6**: generation guard chưa hủy callback đang ghi dở; chưa **re-check project-exists sau khi lấy INDEX_LOCK** trong watcher callback (callback cũ vẫn có thể ghi cho pid đã xoá); **summarizer vẫn ngoài lock**; chưa có deterministic API-concurrency test. → P1-16.
- **P0-5**: collection generation theo embed-model (dimension/config) + inventory/content-hash + summary-embedding version vẫn chưa làm.

### Regression
- Không. 49/49 pass; health chroma true; DB thật nguyên vẹn.
<!-- CLAUDE_REPORT_END -->
