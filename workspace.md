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

- Reviewed implementation commit: 16726fb; report commit: 9f8bbe8.
- Full suite: 40 passed.
- python -m compileall -q codemem: pass.
- node --check web/app.js: pass.
- P0 đã xác minh và đã xóa/thu gọn: typed absent-vs-error vector delete, project existence check trong INDEX_LOCK, roots_canon_v2 re-run + overview invalidation, embed-model check dùng chung cho index/reconcile và các fix vòng trước.
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

- `/api/clear` gọi watcher.stop() **ngoài** INDEX_LOCK. Nếu clear chờ một index đang chạy, index có thể start watcher lại trước khi clear lấy lock; clear sau đó xóa DB nhưng để watcher cũ sống và có thể ghi lại project đã xóa. Chuyển stop vào đầu critical section và thêm race test deterministic.
- Generation guard không dừng callback đã qua bước copy pending và đang ghi; chỉ INDEX_LOCK làm nó chờ, không hủy.
- Summarizer vẫn ngoài lock và có thể ghi summary/vector/overview song song index/delete.
- Error mới chỉ print; chưa vào structured job log/retry.
- Cần deterministic API concurrency tests cho index/select/delete/watcher/summarizer.

### P0-8 — Hoàn thiện canonical-root migration rollout

roots_canon_v2, normcase file dedup và overview invalidation đã đạt. Phần còn lại:

- Vector cleanup vẫn chạy best-effort trước SQLite commit; code bỏ qua cả exception lẫn giá trị False rồi vẫn commit marker v2. Cleanup fail/crash sẽ để orphan vector và migration không retry.
- Không gọi Chroma như side effect không bền trong transaction migration. Ghi cleanup intent/tombstone cùng transaction, commit SQLite trước, rồi worker retry idempotent; chỉ đánh dấu migration hoàn tất khi DB transform + cleanup intent đã durable.
- Có backup/rollback hoặc recovery contract rõ cho schema/data migration.
- Test upgrade thực tế từ DB chỉ có roots_canon_v1=1, cleanup trả False/raise/process interruption, overview merge và junction thật/adapter deterministic.

### P0-10 — Mutation SQLite/vector chưa có partial-result contract

Typed absent/error, boolean response và tombstone file/project cơ bản đã có, nhưng lifecycle vẫn lỗi:

- **Codex repro:** db.clear_all() không xóa vector_tombstones (`1 → 1`). /api/clear thành công hoặc thất bại đều có thể để cleanup cũ sống tiếp sau reset toàn hệ thống.
- /api/clear vector failure không tạo cleanup intent retryable độc lập với project; hiện chỉ trả vector_cleared=false rồi mất khả năng retry tự động.
- list_tombstones luôn lấy 500 ID đầu; nếu 500 mục đầu tiếp tục fail thì mọi mục sau bị starvation vĩnh viễn. Codex repro 501 mục: mục cuối không được thử.
- Tombstone không unique/dedup, không attempts/last_error/next_retry; retry lặp có thể tăng vô hạn và không quan sát được.
- Migration cleanup bỏ qua False/exception và không ghi tombstone; project delete không collapse/clear tombstone file cũ cùng project.
- Thiết kế cleanup intent durable cho scope file/project/collection; dedup + fair batching/backoff; clear phải xóa intent cũ và tạo collection intent mới nếu Chroma clear fail.
- Surface pending/failed cleanup count + last error qua health/API/job/UI; thêm test clear success/failure, >500 poison queue, duplicate, restart và migration cleanup failure.

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
## Vòng — P0-10 durable cleanup-intent (kèm P0-8 cleanup-durable, P0-6 clear-in-lock)

**Commit:** work `5feef23` (report commit ngay sau). **Working tree:** clean sau report.
**Env:** Python 3.12.13 (venv Ollama), chromadb 1.5.9, watchdog 6.0.0.

### Task đã xử lý
- **P0-10 (cleanup-intent đáng tin):**
  - Schema `vector_tombstones` v2: `scope (file|project|collection)` + `attempts` + `last_error` + `next_retry` + `UNIQUE(scope,project_id,file_path)`; migration tự recreate bảng cũ (round trước thiếu cột).
  - `add_tombstone` dùng `INSERT OR IGNORE` → **dedup** (Codex repro duplicate hết). `due_tombstones` **ORDER BY next_retry, id** → chống starvation (>500/poison: item fail bị đẩy next_retry tương lai, item khác được xử lý). `record_tombstone_failure` **exponential backoff** (5s→cap 1h) + lưu `attempts`/`last_error`.
  - `db.clear_all()` **wipe `vector_tombstones`** (Codex repro 1→0); `delete_project` collapse file-tombstone của project.
  - `/api/clear`: nếu `vectors.clear_all()` fail → tạo **collection tombstone** (retry sau), trả `pending_cleanup`; `watcher.stop()` chuyển **vào trong INDEX_LOCK** (#P0-6 — index đang chờ không start lại watcher trước clear).
  - `_retry_tombstones` xử lý cả 3 scope (collection→clear_all, project→delete_project, file→delete_file) + backoff khi fail; chạy trong `reconcile_vectors` (index/switch/manual/startup).
  - `/api/health` surface `cleanup: {pending, failed, last_error}`.
- **P0-8 (migration cleanup durable):** `_migrate_canonical_roots` **không gọi Chroma trong transaction** nữa — ghi cleanup intent bằng `add_tombstones_bulk(conn, ...)` trong **cùng transaction** SQLite (durable), worker retry idempotent sau.

### File/API đã đổi
- `codemem/storage/db.py`: schema v2 + recreate migration; `add_tombstone`/`add_tombstones_bulk`/`due_tombstones`/`record_tombstone_failure`/`del_tombstone`/`tombstone_stats`; `clear_all`+`delete_project` wipe/collapse; migration dùng bulk tombstone.
- `codemem/indexer/runner.py`: `_retry_tombstones` v2 (scope + backoff); callers `add_tombstone(scope,...)`.
- `codemem/api/server.py`: `/api/clear` stop-in-lock + collection tombstone + `pending_cleanup`; delete tombstone signature; health `cleanup` stats.

### Test + kết quả
- `python -m pytest tests -q` → **45 passed** (mới `test_tombstones.py`: dedup, clear-wipe 1→0, backoff-fairness loại item fail khỏi due, project collapse, attempts/last_error; cập nhật retry scopes + backoff).
- `compileall` pass; `node --check web/app.js` pass; server import **25 routes**.
- Real DB: migration recreate `vector_tombstones` đủ cột; DB intact 27 file/pending 0; cleanup stats sạch.

### Partial / chưa làm
- **P0-10**: chưa có **endpoint/job retry tombstone độc lập** (mới chạy ghép trong reconcile) + chưa surface trong **UI**; backoff dùng wall-clock `next_retry` (không có jitter). `/api/clear` khi DB clear xong nhưng vector fail: collection tombstone tạo sau `clear_all` (đã wipe) nên không bị xoá nhầm — OK, nhưng nếu `add_tombstone` lỗi giữa chừng thì mất intent (không bọc cùng transaction với clear).
- **P0-8**: migration vẫn dùng marker boolean `roots_canon_v2` (chưa phải migration-version số + backup/rollback chính thức); chưa test junction thật (chỉ casing/separator); cleanup intent giờ durable nhưng chưa test "process interruption giữa transform và retry".
- **P0-6**: generation guard vẫn **không hủy callback đang ghi dở**; **summarizer vẫn ngoài INDEX_LOCK**; chưa có **deterministic API-concurrency test** (mới unit/DB-level). → gắn **P1-16**.
- **P0-5**: inventory/content-hash đối chiếu vector thật + summary-embedding version vẫn chưa làm.

### Regression
- Không. 45/45 pass gồm toàn bộ test cũ; health chroma true; DB thật nguyên vẹn.
<!-- CLAUDE_REPORT_END -->
