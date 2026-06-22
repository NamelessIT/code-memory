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

- Reviewed implementation commit: 4c511b6; report commit: 76f5a92.
- Full suite: 77 passed.
- python -m compileall -q codemem: pass.
- node --check web/app.js: pass.
- P0 đã xác minh và đã xóa/thu gọn: reconcile-all duyệt mọi project; legacy gen0 được cấp generation thật; startup repair `vec_gen_seq` thiếu/thấp/malformed; generation allocation + file/symbol/edge/route mutation cùng một `BEGIN IMMEDIATE`, rollback/close deterministic và `vector_ok` chỉ đổi khi generation khớp; scheduler cleanup chạy lặp, không tạo duplicate worker và health phân biệt running/busy/stuck; shutdown hook cơ bản và các fix vòng trước.
- Không được làm regression các phần trên.

## TASK DISTRIBUTION — thứ tự triển khai

Claude Code chỉ nhận **một batch tại một thời điểm**, ghi báo cáo và chờ Codex audit trước khi sang batch kế. Không gộp UI/P1 vào batch P0.

1. **NOW — Batch B / P0-6: project lifecycle concurrency.** Đây là task duy nhất của vòng kế tiếp. Watcher/summarizer/reconcile phải fail closed khi project, watcher generation hoặc file generation đã stale; acceptance chi tiết nằm trong P0-6.
2. **NEXT — Batch C / P0-8: migration recovery.** Versioned ledger, explicit transaction/recovery cho `files_new`, backup/rollback contract và interrupted-phase tests.
3. **THEN — Batch D / P0-5 + P0-10: vector truth/inventory.** Collection version theo embedding model, generation-gated Chroma publish/write-order, DB↔Chroma inventory/reconcile mọi project và summary state.
4. **LAST P0 — Batch E / P0-10: Chroma execution boundary.** Real-Chroma integration (`$lte`, missing generation, concurrent write order, delete→recreate), timeout/cancel/process isolation và live restart smoke. Chỉ làm sau khi Batch B–D ổn định.

Codex tiếp tục vai trò audit: chạy repro độc lập, full suite, xóa phần đã đạt và phân phối batch kế.

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
- Thread reconcile được tạo sau project select cũng có thể chờ lock rồi chạy với pid vừa bị delete/switch; `reconcile_vectors()` chưa fail closed cho project không tồn tại.
- Error mới chỉ print; chưa vào structured job log/retry.
- Batch B implementation: watcher `_flush` phải lấy `INDEX_LOCK` rồi re-check watcher generation, bound project ID/root và project existence trước mọi write; `index_single_file`/`remove_file`/`reconcile_vectors` cũng tự fail closed sau khi đã lấy lock, không dựa riêng vào caller.
- Summarizer có thể gọi Ollama ngoài lock, nhưng trước commit summary/vector/overview phải lấy `INDEX_LOCK`, re-check project còn tồn tại và file `vector_gen` vẫn bằng snapshot. File đã re-index/delete hoặc project đã delete thì drop kết quả cũ; không tạo vector/meta mồ côi.
- Cần deterministic Event/Barrier tests: watcher đã copy pending rồi chờ lock → select/delete/stop → callback cũ không ghi; summarizer đang chờ LLM → file re-index/project delete → không ghi summary/vector/overview; reconcile thread stale pid → không gọi Chroma. Test phải kiểm tra cả SQLite, vector fake calls và tombstone side effects.

### P0-8 — Hoàn thiện canonical-root migration rollout

roots_canon_v2, normcase dedup, overview invalidation và cleanup intent cùng transaction đã đạt. Phần còn lại:

- Có backup/rollback hoặc recovery contract rõ cho schema/data migration.
- Marker vẫn là boolean rời rạc thay vì migration version/ledger có transaction và diagnostics.
- files path-PK normal migration đã sửa, nhưng DDL `CREATE files_new` chưa có explicit BEGIN/recovery. Crash sau create trước copy để lại files_new; lần init sau CREATE lại có thể fail. Thêm recovery/ledger và test interrupted ở từng phase.
- Test upgrade thực tế từ DB chỉ có roots_canon_v1=1, transaction rollback/process interruption, overview merge, legacy vector metadata và junction thật/adapter deterministic.

### P0-10 — Mutation SQLite/vector chưa có partial-result contract

Atomic clear, SQL scope filter, forced collection fence và generation guard cho vector mới đã đạt. Các lỗi còn lại:

- SQLite allocation + mutation race của Batch A đã đạt. Phần còn lại: hai process có thể ghi cùng file theo gen 1→2 ở SQLite nhưng Chroma write gen 1 hoàn tất sau gen 2 và ghi đè derived index; conditional `vector_ok` chỉ ngăn DB status bị lật, không ngăn vector cũ trở thành dữ liệu thực tế. Xử lý generation-gated publish/write-order trong Batch D và chứng minh bằng real-Chroma concurrency ở Batch E.
- Chroma trước vòng này có 9 vectors thiếu generation; SQLite marker không tự normalize Chroma. Startup đã reconcile mọi project nhưng chưa có inventory/migration job đối chiếu DB↔Chroma và trạng thái tiến độ.
- Summary generation query đã sửa, nhưng DB summary vẫn không có pending/version state và summarizer race với re-index/delete chưa được bảo vệ.
- Viết integration test bằng Chroma thật cho missing-field + `$lte`, delete→recreate, summary delete và canonical cleanup; fake collection chỉ xác nhận shape where, không xác nhận match/delete semantics. Codex smoke `$lte` trên collection local không hoàn tất trong >30s, cần kiểm tra timeout/performance/lock thay vì để cleanup treo INDEX_LOCK.
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
- `init_db()` và các hàm generation/upsert đã rollback/close deterministic, nhưng nhiều SQLite helper khác vẫn chưa dùng context manager/try-finally; OperationalError giữa mutation có thể để transaction/connection mở và khóa DB trên Windows.

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
- Tests section chưa phản ánh 77 tests và coverage multi-project/migration/vector mới.
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
## Vòng: Batch B / P0-6 — project lifecycle concurrency (fail closed dưới lock)

### Commit / working tree
- Work commit: `a2fff51` (runner.py, watcher.py, summarizer.py, tests/test_reconcile.py,
  tests/test_watcher.py, tests/test_summarizer.py).
- Report commit: chính commit chứa thay đổi workspace.md này.
- Working tree sau report commit: clean (chỉ còn data/ gitignored). Không push.

### Task ID đã xử lý
- **Batch B / P0-6** — callback/job cũ chờ INDEX_LOCK rồi chạy với pid đã delete/switch → tạo lại
  file/vector/overview mồ côi. Watcher/summarizer/reconcile phải **fail closed** khi project, watcher
  generation hoặc file generation đã stale.

### File / schema / API đã đổi
- `codemem/indexer/watcher.py`:
  - Import thêm `from ..storage import db` và `INDEX_LOCK`.
  - `_flush`: sau khi copy pending, **lấy INDEX_LOCK rồi RE-CHECK** `gen == self.generation` **và**
    `db.project_exists(pid)` TRƯỚC mọi write (trước đây chỉ check generation trước khi chờ lock →
    callback cũ vẫn ghi sau stop/switch/delete).
- `codemem/indexer/runner.py`:
  - `index_single_file` / `remove_file`: thêm guard `pid is None or not db.project_exists(pid)` →
    return sớm (tự fail closed trong lock, không dựa caller). `remove_file` không còn ghi tombstone
    mồ côi cho pid đã xóa.
  - `reconcile_vectors`: guard đầu hàm (trước `ensure_embed_current`/Chroma) → trả
    `{repaired:0, pending:0, tombstones_cleared:0, skipped:'project gone'}` cho pid không tồn tại.
- `codemem/indexer/summarizer.py`:
  - Import `INDEX_LOCK`. `run_summarize`: gọi LLM NGOÀI lock; trước khi commit summary/vector thì
    **lấy INDEX_LOCK + re-check** `project_exists(pid)` và `file_vector_state[0] == snap_gen`. File
    đã re-index (gen đổi)/xóa → drop kết quả cũ; project đã xóa → break cả job. `build_overview`:
    `_ask` (LLM) ngoài lock, `set_overview` trong INDEX_LOCK + re-check project_exists.
- Không đổi schema/SCHEMA_VERSION; không thêm/đổi route (vẫn 26).

### Lệnh test + kết quả
- `PYTHONPATH=. PYTHONUTF8=1 python -m pytest tests -q` → **85 passed** (77 baseline + 8 mới; 2 test
  reconcile cũ + 2 watcher cũ cập nhật cho guard project_exists).
- `python -m compileall -q codemem` → pass; `node --check web/app.js` → pass.
- Import smoke: server/watcher/summarizer import sạch (KHÔNG circular), 26 route.
- Test mới:
  - watcher: `test_flush_drops_when_project_deleted` (gen khớp + project gone → không ghi),
    `test_flush_drops_when_generation_advances_after_copy` (switch ngay trước vùng ghi → re-check
    trong lock bỏ).
  - runner: `test_index_single_file_fails_closed_for_deleted_project`,
    `test_remove_file_fails_closed_for_deleted_project` (không tombstone mồ côi),
    `test_reconcile_vectors_fails_closed_for_deleted_project` (guard trước Chroma).
  - summarizer: `test_run_summarize_commits_when_gen_matches` (happy path, vector summary gen đúng),
    `test_run_summarize_drops_when_file_regenerated` (gen lệch → không ghi),
    `test_run_summarize_stops_when_project_deleted` (project xóa → drop, không overview mồ côi).

### Smoke / integration evidence
- Các test trên dùng DB thật (tmp) cho runner/summarizer (SQLite + tombstone side-effect kiểm tra
  thực), vector bằng fake-call để xác nhận KHÔNG gọi Chroma khi stale. Watcher test deterministic
  bằng monkeypatch generation/project_exists + lock wrapper (không cần observer thật).
- Không chạy app full + Ollama vòng này (logic concurrency, không đổi schema).

### Partial / còn thiếu (KHÔNG thuộc Batch B — các Batch sau theo TASK DISTRIBUTION)
- **Batch C / P0-8** — versioned ledger, explicit transaction/recovery cho `files_new`,
  backup/rollback, interrupted-phase tests. CHƯA (batch kế).
- **Batch D / P0-5+P0-10** — collection version theo embedding model, generation-gated Chroma
  publish/write-order, DB↔Chroma inventory/reconcile mọi project, summary pending/version state. CHƯA.
- **Batch E / P0-10** — real-Chroma integration (`$lte`, missing generation, concurrent write order,
  delete→recreate), timeout/cancel/process isolation, live restart smoke. CHƯA.
- **P0-6 còn lại**: lỗi mới vẫn `print` (chưa structured job log/retry) — Codex liệt kê như mục phụ;
  vòng này tập trung fail-closed. Có thể gộp với job system P1-16 sau.

### Regression / phát hiện mới
- Không phát hiện regression mới. 85/85 xanh.
- Lưu ý reviewer thứ tự lock: `_flush` lấy `self._lock` (copy pending) rồi NHẢ, sau đó mới lấy
  `INDEX_LOCK`; KHÔNG giữ đồng thời hai lock → không deadlock với `stop()` (giữ INDEX_LOCK ở API rồi
  gọi watcher.stop() lấy `self._lock`). Trong vùng INDEX_LOCK, `_flush` đọc `self.generation`/`project_id`
  không qua `self._lock` (chỉ để re-check; đã có `project_exists` làm chốt an toàn). Summarizer giữ
  INDEX_LOCK chỉ quanh phần commit (không quanh LLM) nên không block index lâu.
<!-- CLAUDE_REPORT_END -->
