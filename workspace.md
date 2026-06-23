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

- Reviewed implementation commit: 12094ea; report commit: add07a3.
- Full suite: 87 passed.
- python -m compileall -q codemem: pass.
- node --check web/app.js: pass.
- P0 đã xác minh và đã xóa/thu gọn: reconcile-all duyệt mọi project; legacy gen0 được cấp generation thật; startup repair `vec_gen_seq` thiếu/thấp/malformed; generation allocation + mutation cùng một `BEGIN IMMEDIATE`; watcher re-check generation/project sau `INDEX_LOCK`; runner/reconcile fail closed cho project đã xóa; watcher stale timer không xóa pending generation mới; summarizer drop file result khi project mất hoặc file generation đổi; overview stale khi summary đổi trong lúc LLM chạy đã được guard; scheduler cleanup không tạo duplicate và health phân biệt stuck; các fix vòng trước.
- Không được làm regression các phần trên.

## TASK DISTRIBUTION — thứ tự triển khai

Claude Code chỉ nhận **một batch tại một thời điểm**, ghi báo cáo và chờ Codex audit trước khi sang batch kế. Không gộp UI/P1 vào batch P0.

1. **NOW — P0-QR + P0-6 final guard: sửa case retrieval thực tế và khe overview còn sót.** Ưu tiên vì user đã gặp lỗi thật khi hỏi “scanner QR” trên `sukien-myu-vn`. Làm đúng acceptance trong P0-QR, đồng thời vá atomic snapshot gap trong P0-6. Không sang Batch C trước khi hai mục này xanh.
2. **NEXT — Batch C / P0-8: migration recovery.** Versioned ledger, explicit transaction/recovery cho `files_new`, backup/rollback contract và interrupted-phase tests.
3. **THEN — Batch D / P0-5 + P0-10: vector truth/inventory.** Collection version theo embedding model, generation-gated Chroma publish/write-order, DB↔Chroma inventory/reconcile mọi project và summary state.
4. **LAST P0 — Batch E / P0-10: Chroma execution boundary.** Real-Chroma integration (`$lte`, missing generation, concurrent write order, delete→recreate), timeout/cancel/process isolation và live restart smoke. Chỉ làm sau khi Batch B–D ổn định.

Codex tiếp tục vai trò audit: chạy repro độc lập, full suite, xóa phần đã đạt và phân phối batch kế.

## ACTIVE TASKS

### P0-QR — Case thực tế: query “scanner QR” phải tìm đúng hàm/source

User repro: sau khi quét `C:\Github\Code\sukien_myu\sukien-myu-vn`, hỏi **“tìm cho tui hàm có chắc năng scanner qr”** nhưng agent không tìm ra. Codex kiểm tra trực tiếp source ngày 2026-06-23 thấy code QR scanner có thật:

- `src/pages/checkin/nhanquavivu2025.js`: import `QrReader`, xử lý result/error, mở scanner/camera.
- `src/pages/sukien/quayso/dot4/[id].js`: `QrReader`, `extractCCCDFromQR`, `handleScan`, submit CCCD sau khi quét.
- `package.json`: có `react-qr-reader`, `@zxing/library`, `qrcode`, `qrcode.react`.

Codex cũng đọc `data/code_index.db` hiện tại: `projects=0`, `files=168`, `symbols=148674`, chỉ còn meta `vec_gen_seq`, trong khi file/symbol mang `project_id=12`. Đây là state orphan nên `active_project_id()` trả `None` và retrieval scoped theo active project sẽ không thấy symbol nào. Sample files còn rất nhiều `.cache/page-ssr/...`, tức index đang ăn generated cache và làm nhiễu source thật.

Yêu cầu sửa:

- **DB/project integrity:** startup/health phải phát hiện invariant hỏng: có `files/symbols/edges/routes` mang `project_id` không tồn tại trong `projects`, hoặc `active_project_id` không trỏ tới project thật. Không được silent trả search rỗng. Cần repair deterministic: nếu chỉ có một orphan project_id và có thể suy root chung từ file paths thì recreate project + set active; nếu không suy được thì quarantine/purge orphan có log rõ và yêu cầu re-index. Thêm test cho DB có `projects` rỗng nhưng `files/symbols project_id=12`.
- **Generated/cache ignore:** thêm `.cache` tối thiểu, và nên thêm các cache/build phổ biến chưa có (`.gatsby`, `.astro`, `.parcel-cache`, `.turbo`, `.vercel`, `.svelte-kit` nếu phù hợp). Walker phải tôn trọng `.gitignore` khi có thể. Re-index sau khi ignore mới phải remove các file đã index trước đó nhưng nay bị skip, kèm tombstone/vector cleanup; test rằng `.cache/page-ssr/...` bị xóa khỏi DB sau reindex.
- **Lexical retrieval cho query tiếng Việt + tech token ngắn:** tokenizer không được bỏ `qr` chỉ vì dài 2 ký tự; hỗ trợ Unicode/tách dấu cơ bản và CamelCase (`handleScan`, `QRCode`, `QrReader`). Query “scanner QR/quét mã QR/scan qrcode/camera barcode” phải expand/normalize về nhóm intent scan/qr/camera.
- **Search corpus rộng hơn symbol name/signature:** lexical phải tìm trong `symbol.name`, `signature`, `doc`, `body`, file path, skeleton/imports và summary; không chỉ `name LIKE`/`signature LIKE`. Semantic `kind=file|summary` không được bị bỏ phí: nếu semantic trả file/summary thì dùng nó để kéo file liên quan + top symbols/body evidence trong file đó.
- **Ranking/source hygiene:** source thật trong `src/` và symbol người dùng viết phải thắng generated/cache/vendor/icon helper. Nếu cache/vendor bị index sót thì ranking vẫn phải hạ điểm mạnh hoặc loại khỏi context.
- **Acceptance bắt buộc:** thêm fixture hoặc integration mini mô phỏng hai file trên; chạy `build_context("tìm cho tui hàm có chắc năng scanner qr")` phải trả context/sources chứa ít nhất một trong:
  - `src/pages/checkin/nhanquavivu2025.js` với handler xử lý QR scan / `QrReader`;
  - `src/pages/sukien/quayso/dot4/[id].js` với `handleScan` hoặc `extractCCCDFromQR`.
  Không được trả chủ yếu từ `.cache/page-ssr`, icon functions như `TbQrcode`, hoặc generated QR library internals.
- **Live smoke khuyến nghị:** sau khi re-index thật `C:\Github\Code\sukien_myu\sukien-myu-vn\sukien-myu-vn`, `/api/search?q=tìm%20cho%20tui%20hàm%20có%20chắc%20năng%20scanner%20qr` phải có source đúng file `src/...` và answer phải cite line/path. Nếu không chạy được live smoke, báo rõ lý do trong CLAUDE_REPORT.

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

Batch B core + follow-up đã đạt: callback lấy `INDEX_LOCK` rồi re-check generation/project; runner và reconcile tự fail closed; file summary chỉ commit khi project còn và `vector_gen` khớp; stale watcher timer không còn clear pending của generation hiện tại; overview bị drop nếu summary đổi trong lúc LLM chạy. Phần còn lại:

- **Overview atomic snapshot gap:** `build_overview()` hiện đọc `sums = all_file_summaries()` rồi mới tính `rev = summaries_revision()`. Nếu file re-index/xóa summary xảy ra giữa hai lệnh này, body gửi LLM vẫn là summary cũ nhưng `rev` đã là state mới; lúc commit `summaries_revision()==rev` nên vẫn publish overview stale. Codex repro tạm ngày 2026-06-23: monkeypatch `summaries_revision()` lần đầu để `db.upsert_file()` ngay sau khi `sums` đã lấy; expected `get_overview(pid)==''`, actual `"OVERVIEW FROM OLD SUMMARY"`.
- Fix bằng API snapshot atomically, ví dụ `db.all_file_summaries_with_revision(project_id, limit)` đọc `path, vector_gen, summary` trong cùng một connection/query/transaction và trả cả rows + fingerprint tính từ chính rows đó. `build_overview()` phải build body từ rows cùng snapshot, và commit chỉ khi current revision còn bằng snapshot revision.
- Thêm regression test cho “mutation between sums and revision” và giữ test cũ “mutation while _ask is running”. Test project-delete vẫn phải assert `db.get_overview(pid)==''`.
- Error `print`/structured job retry không chặn P0-6; giữ ở P1-16/P1-19.

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
- Tests section chưa phản ánh 85 tests và coverage multi-project/migration/vector mới.
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
5. Realistic retrieval fixtures: Vietnamese, duplicate names, unrelated query, token budgets, và case QR scanner `sukien-myu-vn` (“tìm cho tui hàm có chắc năng scanner qr”).
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
- Query thực tế “scanner QR/quét mã QR” tìm đúng source/hàm scan QR trong project React/Astro, không bị cache/generated code lấn át.
- FastAPI routes và metadata/source coverage được index.
- Model/context UI phản ánh capability thật và hỗ trợ khoảng 32–33k.
- Security/session/path tests pass.
- UI responsive, accessible, có stream abort và source explorer.
- Setup/README/migration tái tạo được.
- Không còn critical exception bị nuốt; full test suite và smoke app pass.

## CLAUDE_REPORT — temporary handoff

<!-- CLAUDE_REPORT_START -->
## Vòng: P0-QR (case 'scanner qr' thực tế) + P0-6 overview atomic snapshot

### Commit / working tree
- Work commit: `2016dcb` (config.py, db.py, search.py, summarizer.py, server.py, tests/test_retrieval.py,
  tests/test_qr.py).
- Report commit: chính commit chứa thay đổi workspace.md này.
- Working tree sau report commit: clean (chỉ còn data/ gitignored — đã re-index thật, xem live smoke).
  Không push.

### Task ID đã xử lý
- **P0-QR** — query "tìm hàm scanner qr" trên `sukien-myu-vn` trả rỗng (DB orphan: projects=0 nhưng
  files project_id=12 → active=None → retrieval scoped rỗng; cache `.cache/page-ssr` làm nhiễu).
- **P0-6** — overview atomic snapshot gap (đọc `sums` rồi mới tính `rev` → khe re-index xen giữa).

### File / schema / API đã đổi
- `codemem/storage/db.py`:
  - **`_repair_orphans(conn)`** (chạy trong `_init_db_impl`): phát hiện files/symbols/edges/routes mang
    `project_id` không có trong `projects`, hoặc `active_project_id` trỏ nhầm. 1 orphan + projects rỗng
    → recreate project (giữ nguyên id) từ `_common_root(file paths)` + set active; nhiều/không suy được
    → `_purge_project_data` + project tombstone + log "cần re-index". Helpers `_common_root`,
    `_purge_project_data`.
  - Legacy single-project migration đổi điều kiện sang `files project_id IS NULL` (không còn tạo
    'legacy-project' giả che mất orphan).
  - **`integrity_status()`** (orphan_files/active_valid/projects) cho health.
  - `search_symbols` mở rộng corpus: name/signature/**doc/body**. **`search_files`** mới: path/skeleton/summary.
  - **`all_file_summaries_with_revision()`** (#P0-6): rows + fingerprint trong 1 query (atomic snapshot);
    `summaries_revision()` giữ cho so sánh lúc commit.
- `codemem/config.py`: IGNORE_DIRS thêm `.cache .gatsby .astro .parcel-cache .turbo .vercel .svelte-kit`.
- `codemem/retrieval/search.py`: tokenizer mới — giữ token 2 ký tự (`qr`), strip dấu tiếng Việt, bỏ
  stopword, expand intent scan/qr/camera/quét/mã; `_candidates` dùng cả semantic kind=file|summary +
  lexical symbol + file; **loại** path generated (`.cache/page-ssr/node_modules/...`) + **hạ điểm** icon
  helper (Tb*/...); rank ascending, src/ ưu tiên nhẹ.
- `codemem/indexer/summarizer.py`: `build_overview` dùng `all_file_summaries_with_revision` (snapshot
  atomic), commit chỉ khi `project_exists` và revision không đổi.
- `codemem/api/server.py`: `/api/health` thêm `integrity`.
- Không đổi SCHEMA_VERSION.

### Lệnh test + kết quả
- `PYTHONPATH=. PYTHONUTF8=1 python -m pytest tests -q` → **95 passed** (87 baseline + 8 mới; cập nhật
  `test_retrieval` stub `search_files`).
- `python -m compileall -q codemem` → pass; `node --check web/app.js` → pass.
- Test mới (tests/test_qr.py): tokenizer giữ `qr`+expand; walker bỏ `.cache`; reindex xóa cache khỏi DB;
  orphan recreate+active / purge nhiều orphan; integrity sạch; **`build_context(...) trả 2 file QR và
  loại generated`**.

### Smoke / integration evidence (LIVE — đã re-index thật)
- Orphan repair trên copy DB thật: projects 0→1, recreate project 12 root
  `c:\github\code\sukien_myu\sukien-myu-vn\sukien-myu-vn`, active=12, integrity sạch.
- **Re-index thật** `C:\Github\Code\sukien_myu\sukien-myu-vn\sukien-myu-vn` (171s): new=197, updated=3,
  skipped=53, **removed=112** (cache/page-ssr bị xóa), errors=0, vector_pending=0; status: files 253,
  **symbols 148674 → 7330** (cache noise biến mất).
- `build_context("tìm cho tui hàm có chắc năng scanner qr")` sau re-index trả sources gồm
  **`src/pages/sukien/quayso/dot4/[id].js`** và **`src/pages/checkin/nhanquavivu2025.js`** (đúng 2 file
  Codex nêu), không có `page-ssr`/`.cache`; context có `handleScan`/`extractCCCDFromQR`/`QrReader`.
  → ĐẠT acceptance bắt buộc P0-QR.

### Partial / còn thiếu
- Lexical vẫn dùng LIKE (chưa FTS5/BM25 — đó là P1-11, ngoài phạm vi P0-QR). Ranking là heuristic
  (penalty path + icon prefix), chưa BM25-scored.
- **Batch C / P0-8** (migration ledger/recovery `files_new`, backup/rollback, interrupted-phase) — CHƯA.
- **Batch D / P0-5+P0-10** (collection version theo embed model, generation-gated Chroma publish/
  write-order, DB↔Chroma inventory mọi project, summary pending/version state) — CHƯA.
- **Batch E / P0-10** (real-Chroma integration `$lte`/missing-gen/concurrent-order, timeout/cancel/
  process isolation, live restart smoke) — CHƯA.

### Regression / phát hiện mới
- Không phát hiện regression. 95/95 xanh. `/api/health` thêm field `integrity` (additive).
- Phát hiện khi smoke: index trước đây ăn `.cache/page-ssr` → 148674 symbols (đa số là noise);
  sau ignore + re-index còn 7330. Đây là nguyên nhân chính làm retrieval loãng, nay đã sạch.
- Lưu ý reviewer: re-index thật đã ghi vào `data/` (gitignored). Nếu Codex muốn tái lập trạng thái
  orphan để audit `_repair_orphans`, dùng test `tests/test_qr.py::test_repair_orphan_project_recreates_and_activates`
  (deterministic) thay vì DB thật (đã được sửa bởi smoke).
<!-- CLAUDE_REPORT_END -->
