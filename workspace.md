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

- Reviewed commit: 31a2a5b.
- Full suite: 24 passed.
- python -m compileall -q codemem: pass.
- node --check web/app.js: pass.
- P0 đã xác minh và đã xóa khỏi task list: overview API per-project, /api/file 500, overview invalidation, degraded fallback cơ bản, watcher stop/debounce/moved cơ bản, summarizer bind project, SQLite nested-project isolation, project ID validation/fallback.
- Không được làm regression các phần trên.

## ACTIVE TASKS

### P0-5 — Vector reconciliation/retry sau khi SQLite đã commit

Hiện runner commit db.upsert_file() trước vectors.index_file() và bỏ qua giá trị False của index_file().

- Nếu embedding add lỗi, hash SQLite đã mới nên lần index sau file bị skip dù vector thiếu/stale.
- Thêm trạng thái vector_pending/vector_version hoặc outbox/reconciliation idempotent.
- File unchanged nhưng vector pending phải được retry.
- Health/job/UI phải cho biết lexical-only, pending và repair result.
- Thêm test DB success + vector failure + lần index sau repair thành công.

### P0-6 — Watcher/index concurrency vẫn phụ thuộc active project toàn cục

Các fix stop timer/pending, moved event và case-insensitive ignore đã có. Phần còn lại:

- Watcher phải bind project_id + root/generation tại lúc start; index_single_file/remove_file không được tự đọc active project toàn cục.
- Timer callback đã bắt đầu trước stop không được ghi vào project mới.
- Serialize hai request index đồng thời, watcher flush và project delete/reindex xung đột.
- _flush/index_single_file/remove_file vẫn nuốt exception; lỗi phải log/job retry được.
- Thêm deterministic concurrency tests.

### P0-8 — Vector delete vẫn làm leak giữa nested projects

SQLite composite identity đã đúng, vector IDs đã có project_id. Nhưng:

- vectors.delete_file(path) chỉ filter file_path.
- vectors.index_file() gọi delete_file(path), nên update file của project A có thể xóa embeddings cùng absolute path của project B.
- runner remove cũng gọi vector delete không truyền project_id.

Sửa delete/update theo cả project_id + file path hoặc stable project-scoped IDs. Thêm regression test chứng minh update/delete A không ảnh hưởng B.

Ngoài ra canonicalize project root theo Windows (drive/case/separator/symlink policy) để cùng thư mục không tạo project trùng.

### P0-10 — Mutation SQLite/vector chưa có partial-result contract

- Delete project/clear có thể xóa SQLite thành công nhưng vector fail, để orphan embedding.
- clear_all không trả success/failure chi tiết.
- /api/clear vẫn giữ chat history sau khi evidence/project bị xóa.
- Thiết kế result/retry/reconciliation; reset hoặc rebind chat session đúng project.
- Destructive UI phải hiển thị partial failure thay vì luôn báo thành công.

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
- Tests section chưa phản ánh 24 tests và coverage mới.
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
## Vòng triển khai — P0-5, P0-6, P0-8, P0-10 (reliability + project-scoped lifecycle)

**Commit:** work ở `9af630e` (report commit ngay sau). **Working tree:** clean sau report commit.
**Môi trường:** Python 3.12.13 (venv Ollama), chromadb 1.5.9, tree-sitter-language-pack, watchdog 6.0.0.

### Task đã xử lý
- **P0-8 (vector leak nested):** `vectors.delete_file(path, project_id)` chỉ xoá trong project (`where {$and:[file_path, project_id]}`); `index_file` gọi delete kèm `project_id`; vector IDs đã có prefix `project_id`; canonicalize root (`os.path.normcase/normpath/realpath`) + normcase file path trong runner → cùng thư mục không tạo project trùng.
- **P0-5 (vector reconciliation):** thêm cột `files.vector_ok`; runner set sau `index_file`; `reconcile_vectors(pid)` retry file pending (kể cả file unchanged từng lỗi vector); `get_status().vector_pending` + `index_project` trả `vector_repaired/vector_pending`.
- **P0-6 (watcher bind project):** `WatcherManager` giữ `project_id` + `generation`; `_flush(gen)` bỏ qua khi generation stale (sau switch/stop) → không ghi vào project mới; `index_single_file/remove_file(path, project_id)` bind cứng pid (không đọc active toàn cục); `watcher.start(root, project_id)` ở index/select/delete/startup.
- **P0-10 (partial-result):** `vectors.clear_all/delete_file/delete_project` trả bool; `/api/clear` stop watcher + reset chat session + trả `{sqlite_cleared, vector_cleared}`; `/api/project/delete` trả `vector_deleted`.

### File/schema/API đã đổi
- `codemem/storage/db.py`: cột `files.vector_ok` (+migration, +files_new recreate); `set_vector_ok/files_pending_vector/get_project_root`; `delete_file(path, project_id)`; `get_status.vector_pending`.
- `codemem/storage/vectors.py`: `delete_file(path, project_id)` + return bool; `index_file` delete scoped; `clear_all/delete_project` return bool.
- `codemem/indexer/runner.py`: `canonical_root`, `_index_one` (set vector_ok), `reconcile_vectors`, `index_single_file/remove_file` nhận `project_id`, normcase paths.
- `codemem/indexer/watcher.py`: bind `project_id`+`generation`, `_flush(gen)` guard, truyền pid.
- `codemem/api/server.py`: `watcher.start(..., project_id)` ở 4 chỗ; `/api/clear` + `/api/project/delete` partial-result + reset session.

### Lệnh test + kết quả
- `python -m pytest tests -q` → **31 passed** (mới: `test_watcher.py` 3, `test_reconcile.py` 2, vector delete-scoping 2 trong `test_vectors_degraded.py`).
- `python -m compileall -q codemem` → pass. `node --check web/app.js` → pass. Server import: **24 routes**.

### Integration evidence
- Nested: index A=`outer/sub`, B=`outer` (gồm `sub/x.py`). Reindex A sau khi sửa file → **B vẫn thấy symbol** (vector B không bị xoá). `vector_pending=0` sau index repo (27 file).
- `/api/project/select {id:999999}` → **404** (đã verify vòng trước, không regression).

### Partial / chưa làm
- P0-6 "serialize hai request index đồng thời": chưa có lock toàn cục cho index/watch/delete chạy song song — generation guard chỉ chống stale flush, chưa chống 2 `/api/index` đồng thời (cần global index lock — gắn với P1-16 background jobs). Concurrency test deterministic mới có cho watcher flush, chưa có cho 2 index job song song.
- P0-5: chưa có outbox bền vững qua restart; reconcile chạy cuối mỗi `index_project` + có thể gọi thủ công, nhưng chưa có endpoint `/api/reconcile` riêng và chưa surface ra UI.
- P0-10: chưa rebind chat session theo project sau partial-failure (mới reset); chưa có retry UI.

### Regression/phát hiện mới
- (Tự phát hiện & đã fix trong vòng này) `clear_all`/`_raw` bản trước tạo collection KHÔNG embedding-function → ghi đè ef config thành "default" → `get_collection` (sentence_transformer) xung đột → degraded oan. Đã sửa: `_raw` dùng `get_collection` (retrieve, không cấp ef); `clear_all` chỉ `delete_collection` rồi reset, để lần sau tạo lại đúng ef. Verify: health `chroma:true, embedding_failed:false`, semantic OK.
<!-- CLAUDE_REPORT_END -->
