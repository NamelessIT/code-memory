# Prompt triển khai cho Claude Code — code-memory

Bạn là kỹ sư triển khai chính cho repository `code-memory`. Hãy đọc toàn bộ repository hiện tại trước khi sửa, sau đó thực hiện các yêu cầu dưới đây. Không chỉ viết kế hoạch: hãy sửa code, thêm migration/tests, chạy kiểm tra thật và báo cáo những gì đã hoàn thành/chưa hoàn thành.

## 1. Mục tiêu sản phẩm

Biến `code-memory` thành bộ nhớ codebase local đáng tin cậy cho agent Qwen nhỏ, context tối đa khoảng 32–33k token. Sau lần quét đầu, agent phải có thể recall mà không quét lại toàn bộ project:

- file, module, cấu trúc thư mục;
- function/method/class/interface/type và chức năng của chúng;
- chữ ký, vị trí dòng, qualified name, quan hệ cha/con;
- imports/dependencies, inheritance/implements và call graph có định danh rõ ràng;
- workflow/luồng nghiệp vụ;
- API endpoint, handler, middleware, request/response liên quan;
- event/listener/producer/consumer;
- architecture/tầng/module và các điểm vào chính;
- dấu hiệu security/config/env quan trọng;
- lịch sử index, độ mới và nguồn chứng cứ.

Mọi thứ chạy local. Không gửi source code hoặc memory ra cloud. Model/embedding phải cấu hình được, không hard-code theo máy của tác giả.

## 2. Hiện trạng đã kiểm chứng (không giả định)

Audit ngày 2026-06-20 đã đọc toàn bộ source và chạy app thật bằng venv mà `start.bat` dùng.

### P0 — lỗi làm sai mục tiêu sản phẩm

1. `codemem/config.py` hard-code `MODEL="agent-7b-v2"`, `NUM_CTX=8192`; UI cũng hard-code badge model. Ollama thực tế báo `agent-7b-v2:latest` là Qwen2, 7.6B, context 32768. Nếu người dùng muốn Qwen 2B thì app hiện không chọn/dò được model đó.
2. `codemem/indexer/runner.py:18-22` xóa toàn bộ SQLite + Chroma khi đổi project. Schema không có `project_id`; app chỉ là one-project-at-a-time, không phải memory nhiều codebase.
3. Index chính repository này chỉ thu được 1 file (`web/app.js`), 13 symbols; toàn bộ Python/HTML/CSS bị bỏ qua. Hiện chỉ hỗ trợ JS/JSX/MJS/CJS/TS/TSX/C#.
4. DB chỉ lưu skeleton/signature, không lưu code chunk/docstring/comment/body có giới hạn. Vì vậy không đủ chứng cứ để giải thích “hàm/class làm gì”. Tóm tắt file cũng chỉ nhìn skeleton.
5. Chat test với câu `Explain indexProject using only indexed context and cite the file.` đã bịa rằng hàm dùng “OpenAI embedding”, rồi bịa các file `api/project.js`, `models/project.ts`, `tests/project.test.ts`.
6. Overview do chức năng “Tóm tắt” sinh ra đã bịa MongoDB, Redis, Socket.IO, `chatService`, `projectService`, repository/validator và workflow không tồn tại. Overview này được lưu vào `meta` và chèn lại vào system context, làm hallucination trở thành memory lâu dài.
7. Semantic search luôn trả top-N nhưng không trả/kiểm tra distance; query không liên quan như “architecture project” vẫn nhận các hàm UI. Keyword search dùng cả câu hỏi làm một chuỗi `LIKE`, nên gần như vô dụng cho câu hỏi tự nhiên.
8. Summary/overview không bị invalidated khi file đổi. `upsert_file()` giữ nguyên `files.summary`; `files_needing_summary()` vì vậy bỏ qua summary cũ. Vector summary và overview cũng có thể stale.
9. Nếu SQLite upsert thành công nhưng Chroma add thất bại, hash đã được cập nhật; lần index sau file bị skip và vector không tự hồi phục.
10. `IGNORE_DIRS` chứa `packages`, làm mất source của nhiều monorepo. Walker không đọc `.gitignore`, không báo file bị skip và kiểm tra tên thư mục phân biệt hoa/thường.

### P0/P1 — độ chính xác dữ liệu

1. Call graph chỉ lưu `caller`/`callee` bằng simple name, không project/file/qualified symbol ID. Built-in/library calls như `trim`, `fetch`, `map`, `await` bị trộn với internal calls; overload/name collision bị gộp sai.
2. Khi vector candidate thiếu signature, retrieval gọi `get_symbols_by_name(name, limit=1)` mà không ràng buộc file, nên có thể lấy signature của definition khác.
3. Tag FE/BE dùng substring trên absolute path. Vì đường dẫn có thư mục `Repository`, hint `"/repositor"` khiến mọi function trong `web/app.js` bị tag `be`.
4. Route parser chỉ bao phủ một phần Express và ASP.NET attribute. Không có FastAPI/Flask/Django, NestJS, Next.js route, ASP.NET controller prefix; handler Express đang ghi caller thay vì handler argument.
5. Không có import/dependency graph thực sự, inheritance graph, event graph, workflow artifacts hoặc security facts có provenance.
6. `all_file_summaries(limit=200)` và overview chỉ lấy 150 file, dùng basename nên project lớn bị cắt âm thầm và trùng tên file.
7. Context budget dùng character thay vì token. `MAX_HISTORY_CHARS` cũng vậy. Không có tổng budget bao gồm system + brain + history + evidence + output reserve.
8. Brain lessons được đưa trước code context, không có score threshold; nội dung ngoài code có thể lấn át chứng cứ dự án.
9. Source/summary là dữ liệu không tin cậy nhưng được chèn vào system prompt; chưa có ranh giới/provenance/chống prompt injection.

### P1 — lifecycle, concurrency, reliability

1. Index chạy blocking trong HTTP request, không có job ID/progress/cancel/chi tiết lỗi.
2. Watcher cũ chỉ bị stop sau khi index project mới xong; có race với wipe/index. `/api/clear` không stop watcher, nên file thay đổi sau clear có thể tự chui lại vào DB rỗng.
3. Startup gọi watcher cho path cũ trước khi uvicorn chạy; path không còn tồn tại có thể làm app không khởi động.
4. Watcher, summarizer, index endpoint và chat có thể truy cập SQLite/Chroma đồng thời nhưng không có chiến lược serialize/lock rõ ràng; nhiều `except Exception: pass` che mất lỗi.
5. Summarizer lưu chuỗi `(loi tom tat: ...)` như summary hợp lệ rồi vector hóa; UI vẫn báo thành công.
6. Chat session là singleton toàn server, không persist, reset ảnh hưởng mọi tab; đổi/clear project không reset hoặc tách history nên context cũ có thể nhiễm project mới.
7. `vectors.clear_all()` nuốt lỗi. Trong `data/vector_index` đã quan sát nhiều thư mục HNSW orphan không còn khớp segment hiện tại.
8. `vectors.clear_all()` gọi `get_collection()` nên thao tác clear rỗng vẫn khởi tạo SentenceTransformer, load weights và có thể chạm Hugging Face Hub; clear/delete không được phụ thuộc việc embedding model tải thành công.
9. Python hệ thống thiếu dependency; app sống nhờ đường dẫn venv hard-code `C:\Agent\Agent_Ollama\Ollama\.venv`. Venv đó không có module `pip`. Requirements không lock version, chưa có packaging/health check tốt.
10. Không có test suite, CI, formatter/linter config hay migration version chính thức. `compileall` và `node --check web/app.js` hiện pass, nhưng đó chưa đủ.

### P1 — API/security

1. Server bind localhost là tốt, nhưng các POST không body như `/api/clear`, `/api/reset`, `/api/summarize` có thể bị website khác submit kiểu CSRF vào localhost. Không có Origin/Host/session nonce protection.
2. `/api/index` cho phép index bất kỳ thư mục process đọc được; cần explicit local trust boundary, path normalization, allowlist/recent-project approval và chống symlink escape phù hợp.
3. Input không có giới hạn độ dài; lỗi nội bộ/Ollama bị trả thẳng; FastAPI docs mặc định mở; không có request ID/audit log.
4. Nội dung codebase có thể chứa prompt injection. Summary và chat phải coi source/comment là evidence data, không phải instruction.

### P1/P2 — UI/UX/accessibility

1. Header là một hàng gồm path + 6 nút, không wrap và không có media query; chắc chắn overflow ở màn hình hẹp. Dùng `100vh`, chưa tối ưu mobile keyboard (`100dvh`).
2. UI không có project library/switcher, project health/freshness, index progress, error list, cancel/retry, model/embedding status hoặc token budget.
3. Sources chỉ là chip text, không click để xem file/symbol/snippet. Routes bỏ file/line dù API có dữ liệu. Không có structure/workflow/graph explorer.
4. Không có loading indicator khi chờ token, stop generation, retry, copy, abort controller; SSE parser bỏ final buffer và chưa xử lý HTTP error/JSON lỗi chắc chắn.
5. Các example chip là `span`, tooltip chỉ hover, send button thiếu accessible label, focus state nghèo, không có `prefers-reduced-motion`.
6. Model badge hard-code, project path không được restore vào input, lỗi polling summarize có thể lặp vô hạn.
7. Không kiểm tra trực quan bằng browser được trong audit vì Windows chặn tiến trình browser automation; Claude Code phải tự render/test desktop + mobile sau khi sửa.

## 3. Kiến trúc đích tối thiểu

Không cần over-engineer thành distributed system. SQLite vẫn là source of truth local; vector store là index có thể rebuild. Thiết kế migration rõ ràng, không phụ thuộc dữ liệu Chroma cũ.

### 3.1 Project-scoped, versioned memory

Thêm các khái niệm/schema tương đương:

- `projects`: stable ID, canonical root, display name, created/last indexed timestamps, active flag, parser/index schema version, git head/branch nếu có, status.
- `files`: `project_id`, relative path, canonical path (nếu cần nội bộ), lang, content hash, size, mtime, parse status/error, indexed version, summary status/version.
- `symbols`: stable ID, file ID, kind, name, qualified name, parent symbol ID, signature, docstring/comment, start/end lines, exported/visibility, tags, content hash.
- `chunks`: file/symbol scope, line range, compact source text, chunk type, token estimate, content hash. Không vector hóa secrets/generated/vendor files.
- `relationships`: typed source/target IDs và confidence/provenance (`calls`, `imports`, `inherits`, `implements`, `contains`, `registers_route`, `emits`, `listens`, ...). External/unresolved target phải đánh dấu rõ, không giả làm internal symbol.
- `routes`: project/file/symbol IDs, framework, method, normalized/full path, handler, middleware, line, confidence.
- `facts` hoặc bảng chuyên biệt cho architecture/workflow/security/config với evidence file+line, generator version và confidence.
- `summaries`: scope/type, text, source hash set, model, prompt version, generated time, status/error; stale khi bất kỳ dependency đổi.
- `index_jobs`/`index_errors`: progress, skipped reasons, failure details, started/finished/cancelled.

Mọi query phải scope bằng `project_id`. Không xóa project khác khi switch. Có thao tác xóa riêng từng project và “rebuild vector index”. Tránh absolute path trong prompt; ưu tiên project name + relative path.

### 3.2 Indexing

1. Hỗ trợ tối thiểu Python + ngôn ngữ hiện có. Thiết kế registry để thêm ngôn ngữ/framework dễ dàng. Nên index thêm các file metadata có ích (README/Markdown, JSON/YAML/TOML, HTML/CSS, SQL) ở mức chunk/config, dù không phải tất cả đều có symbol AST.
2. Tôn trọng `.gitignore` và danh sách ignore cấu hình; không ignore toàn bộ `packages`. Skip binary/generated/minified/large file có reason và thống kê.
3. Lưu đủ evidence để agent giải thích chức năng: signature + docstring/leading comment + source body/chunk có giới hạn. Không chỉ skeleton.
4. Index incremental theo content hash + parser/schema/prompt version. File đổi phải invalidate symbol/chunk/vector/summary/workflow/overview liên quan.
5. SQLite commit và vector update phải idempotent/recoverable. Vector là derived index; có reconciliation job phát hiện thiếu/thừa/stale embedding.
6. Chỉ summarize từ evidence. Prompt summary bắt buộc ghi `unknown/not found` thay vì suy diễn. Validation hậu kỳ phải loại entity/technology không xuất hiện trong evidence hoặc đánh dấu inference rõ ràng.
7. Overview/workflow nên build phân cấp (symbol → file → module → project), có evidence IDs và hỗ trợ project >150 file; không truncate âm thầm.
8. Chọn embedding qua config. Nếu dùng `all-MiniLM-L6-v2`, ghi rõ hạn chế với query tiếng Việt/code; cho phép backend Ollama hoặc model multilingual/code khác mà không bắt buộc download ngầm. App phải hoạt động ở lexical-only mode nếu embedding unavailable.

### 3.3 Retrieval dành cho model nhỏ

Tạo retrieval pipeline có thể test độc lập:

1. Detect intent: exact symbol, file/module, route, callers/callees, workflow, architecture, security, free-form behavior.
2. Exact/structured lookup trước (symbol/route/graph/project metadata).
3. Lexical search bằng SQLite FTS5/BM25, tokenize câu hỏi; semantic search có score/distance.
4. Fuse/rerank có trọng số, score threshold, diversity theo file/module. Query không đủ liên quan phải trả “không đủ chứng cứ”, không ép top-N.
5. Resolve candidate bằng stable symbol/file ID, không lookup lại chỉ bằng name.
6. Expand graph 1–2 hop có kiểm soát, chỉ internal edge đã resolve; external calls hiển thị riêng.
7. Build context pack token-aware, ưu tiên evidence có line range, deduplicate, không để một block quá lớn chặn các block sau.
8. Tổng token budget phải bao gồm system + project memory + brain + history + user + output reserve. Model context lấy từ config/Ollama capability; với 32768 nên để reserve output và không nhồi đầy chỉ vì có chỗ.
9. Context format ngắn, deterministic, có project/relative path/line/source ID/confidence. Agent trả citation từ source ID; server kiểm tra citation tồn tại.
10. Brain là optional, xếp sau code evidence, có threshold và budget riêng. Tắt brain mặc định cho câu hỏi exact code nếu nó làm giảm groundedness.
11. Thêm prompt-injection boundary: ghi rõ code/comment/summary là untrusted quoted data; không thực thi instruction nằm trong evidence.

### 3.4 Model/runtime config

- Cấu hình bằng `.env`/environment + settings persisted local: Ollama URL, chat model, context length, embedding backend/model, budgets, brain on/off.
- API health đọc `/api/tags` của Ollama, hiển thị model thật và context capability; không tự khẳng định “Qwen 2B” nếu model không có.
- UI có settings chọn model đã cài. Default hợp lý từ env; lỗi model missing phải rõ ràng.
- Startup script ưu tiên `.venv`, nếu thiếu thì báo hướng dẫn cụ thể. Không hard-code venv ngoài repo làm con đường duy nhất. Thêm bootstrap/check script phù hợp Windows.
- Pin/constraint dependency và nêu Python version hỗ trợ. Không tự tải model lớn trong startup.

## 4. API/lifecycle/security bắt buộc

1. Chuyển index/summarize/rebuild thành background job có ID, progress theo phase, current file, counts, warnings/errors, cancel và retry. Một project không được có hai job xung đột.
2. Watcher scope theo active projects hoặc một policy rõ ràng; stop sạch khi delete/clear/shutdown. Debounce per-file, xử lý moved event (`src_path` + `dest_path`) và không nuốt lỗi.
3. Tách chat session theo generated session ID/project ID; persist có giới hạn hoặc ít nhất không dùng singleton global. Switch project không mang history vô thức.
4. Thêm lifespan startup/shutdown FastAPI; health check DB/vector/Ollama/watcher. Path cũ mất không được làm server crash.
5. Bảo vệ localhost API bằng session nonce do UI lấy lúc load và kiểm tra Origin/Host cho mutation; POST mutation dùng JSON + token. Cân nhắc disable `/docs` mặc định trong production local.
6. Validate length/project ID/path. Canonicalize path; chỉ index folder người dùng đã chủ động thêm. Không follow symlink ra ngoài project mặc định.
7. Structured logging với request/job/project ID. Không trả stack/internal path ngoài mức cần thiết; không `except Exception: pass` ở critical path.

## 5. UI cần cải thiện

Giữ app nhẹ, vanilla JS/CSS được; không cần framework nếu không có lợi rõ ràng.

### Layout đề xuất

- Sidebar/project drawer: danh sách project đã nhớ, trạng thái fresh/stale/indexing/error, chọn/switch/delete/reindex.
- Main area có tab hoặc panel: Chat, Explorer, Routes, Workflows/Architecture, Issues/Index log.
- Top status: model thật, Ollama/embedding health, project hiện tại, last indexed, số file/symbol/chunk, watcher status.
- Composer chat: loading, stop generation, retry/copy, token/context usage; sources click được mở evidence panel (relative path, lines, snippet, reason/score).
- Index modal/panel: folder path, ignore preview, ngôn ngữ tìm thấy, progress/cancel, warning skipped files.

### Chất lượng UI

- Responsive thật ở 360/768/1024/1440 px; toolbar wrap/collapse; dùng `min-width:0` và `100dvh`.
- Semantic buttons thay `span`, `aria-label`, keyboard navigation, `:focus-visible`, tooltip dùng được bằng focus, reduced motion.
- Không dùng `alert()` cho luồng chính; dùng toast/inline error. Destructive action xác nhận tên project.
- SSE parser robust hoặc dùng NDJSON rõ ràng; xử lý `response.ok`, final buffer, malformed event, disconnect và AbortController.
- Sanitize markdown an toàn. Nếu thêm thư viện renderer, pin version và không bật raw HTML.
- Routes/structure có filter/search và hiển thị file:line; không cắt dữ liệu âm thầm.
- Không báo “summary thành công” nếu có file lỗi; hiển thị partial success và retry.

## 6. Tests bắt buộc

Tạo test suite có fixture nhỏ, không cần Ollama thật cho unit/integration test; mock chat/embedding deterministic.

1. Parser tests cho JS/TS/TSX/C#/Python: functions, classes, methods, nested/overload/qualified names, imports, inheritance, routes theo framework hỗ trợ, events; parse error/empty file.
2. Regression test: absolute path chứa `Repository` không được biến UI JS thành backend.
3. Project isolation: index A rồi B vẫn giữ A; switch/search/delete chỉ tác động project được chọn.
4. Incremental/staleness: đổi body nhưng giữ tên phải cập nhật chunk/vector và invalidate/regenerate summary + overview.
5. Vector failure sau DB write phải được reconciliation/retry; lexical-only fallback vẫn search được.
6. Retrieval relevance: exact symbol đúng file; duplicate names không lẫn signature; unrelated query trả insufficient evidence; source list khớp mọi evidence trong context.
7. Call graph không coi built-in/external là internal; same-name methods ở class/file khác không bị gộp.
8. Grounding test: fixture không có MongoDB/Redis/Socket.IO thì overview không được sinh các technology đó. Mock LLM cố bịa phải bị validator reject/mark unsupported.
9. Token budget test ở model context 8192 và 32768; không vượt budget, giữ output reserve, history trim theo message pair/token.
10. API tests: invalid/missing path, job progress/cancel, project-scoped endpoints, session isolation, CSRF/origin/token, body length limits, watcher clear/shutdown.
11. UI smoke tests desktop/mobile: no horizontal overflow, keyboard focus, project switch, index progress, chat stream abort, source drawer.
12. Migration test từ DB hiện tại. Vì current overview có thể hallucinated, migration phải đánh dấu legacy summaries/overview stale hoặc yêu cầu rebuild; không tin chúng mặc định.

## 7. Acceptance criteria

Không xem là hoàn thành nếu chỉ đổi UI hoặc tăng `NUM_CTX`.

- Index repository `code-memory` phải bao phủ Python + JS + HTML/CSS/README ở mức phù hợp, không còn 1/17 source như audit.
- Có thể giữ và tìm kiếm ít nhất hai project độc lập sau restart.
- Hỏi về `codemem.indexer.runner.index_project` phải trả đúng chức năng từ source, citation relative path + line, không bịa OpenAI/files/services.
- Hỏi architecture của chính repo phải nêu FastAPI, SQLite, Chroma, tree-sitter, Ollama, web UI dựa trên evidence; không nêu MongoDB/Redis/Socket.IO.
- Query vô nghĩa/unrelated phải trả insufficient evidence hoặc confidence thấp, không trả context tùy tiện.
- File đổi phải cập nhật memory incremental và không dùng summary/overview cũ.
- App vẫn usable khi Chroma/embedding/Ollama tạm unavailable: index lexical được, health báo degraded; chat báo lỗi có hướng dẫn.
- Model badge/settings phản ánh model Ollama thật và context config thật.
- Không có critical exception bị nuốt; UI thấy lỗi index theo file.
- Test suite pass và có lệnh chạy rõ trong README.

## 8. Cách triển khai và báo cáo

1. Trước khi sửa: ghi ngắn current architecture và migration plan.
2. Chia commit/work thành phase an toàn nếu cần, nhưng ưu tiên P0 memory correctness trước UI polish.
3. Giữ compatibility endpoint nếu hợp lý; nếu đổi API, cập nhật UI/README cùng lúc.
4. Không xóa dữ liệu người dùng âm thầm. Backup DB trước migration; có đường rollback/rebuild vector.
5. Sau khi sửa, chạy toàn bộ tests/lint/type/syntax checks, khởi động app thật, index chính repo, thực hiện các acceptance query và render UI ở desktop/mobile.
6. Báo cáo cuối gồm: file đã đổi, migration, commands/tests + kết quả, số file/symbol/chunk index được, ví dụ grounded answer, ảnh/UI checks, hạn chế còn lại.

Nếu phạm vi quá lớn cho một lượt, vẫn phải hoàn thành một vertical slice P0 chạy được (multi-project schema + Python indexing + evidence chunks + grounded retrieval + stale invalidation + tests), rồi ghi TODO cụ thể cho phase sau. Không che lỗi bằng catch-all và không dùng LLM-generated summary làm source of truth nếu thiếu provenance.

---

# 9. BÁO CÁO TRIỂN KHAI — Claude Code (2026-06-20)

## 9.1 Xác nhận audit
Đã đối chiếu trực tiếp source. **Audit chính xác.** Các claim P0 kiểm chứng được: không index Python (`config.py` thiếu `.py`), `packages` trong `IGNORE_DIRS`, tag dùng substring `/repositor`, summarizer lưu chuỗi `(loi tom tat: ...)` làm summary, runner wipe khi đổi project, `MODEL` hard-code. Các claim grounding (#5/#6 bịa OpenAI/MongoDB/file giả), retrieval không có distance threshold, stale summary, đều đúng.

## 9.2 Đã triển khai (vertical slice P0 — "memory đáng tin" + Python + config + tests)
- **Index Python** (+ giữ JS/TS/TSX/C#): `config.py` thêm `.py`; `parser.py` thêm `function_definition`/`class_definition`, method-trong-class, call `attribute`, import `import_from_statement`, docstring Python.
- **Evidence thật** (không chỉ skeleton): `symbols` thêm cột `doc` + `body` (thân hàm giới hạn `MAX_BODY_CHARS`); đưa vào context dưới mục `EVIDENCE`; summarizer + embedding dùng kèm doc.
- **Grounded retrieval** (`retrieval/search.py`): semantic có **distance threshold** (`SEMANTIC_MAX_DISTANCE`), lexical **tokenize câu hỏi** (không LIKE cả câu), **trả rỗng = "không đủ chứng cứ"** thay vì ép top-N; signature lookup **file-scoped** (`get_symbol_in_file`); call graph **chỉ giữ edge nội bộ** (`symbol_exists`, loại built-in/external); output dùng **relative path**.
- **Chống hallucination ở prompt** (`chat/agent.py`): evidence là DỮ LIỆU TRÍCH DẪN (chống prompt injection), cấm bịa công nghệ/file, thiếu chứng cứ phải nói rõ; brain xếp SAU code evidence, đánh dấu là tham khảo phụ.
- **Summary grounded** (`summarizer.py`): prompt cấm suy diễn công nghệ; **KHÔNG lưu chuỗi lỗi làm summary** (lỗi → bỏ qua, đếm error); overview chỉ từ file summary.
- **Stale invalidation**: `upsert_file` xoá `summary` khi file đổi → tự tóm tắt lại; đổi `SCHEMA_VERSION` → xoá overview + reset summary cũ (loại hallucination legacy).
- **Tag fix**: `_compute_tag` dùng **relative path + khớp segment chính xác** (runner truyền rel path); thư mục tổ tiên `Repository` không còn làm web JS thành `be`.
- **Config model không hard-code**: `MODEL`/`NUM_CTX`/`OLLAMA_URL`/`EMBED_MODEL`/budget qua env `CODEMEM_*`; endpoint **`/api/models`** đọc model thật từ Ollama `/api/tags`; `/api/status` trả `model`+`num_ctx`; UI badge hiển thị model thật.
- **Walker**: ignore không phân biệt hoa/thường; bỏ `packages`/`Migrations` khỏi ignore.
- **Lifecycle**: `/api/clear` **stop watcher** trước khi xoá (chống race); startup chỉ bật watcher nếu path còn tồn tại (`os.path.isdir`); `vectors.query` trả distance; `vectors.available()` cho lexical-only/degraded.

## 9.3 Migration
`SCHEMA_VERSION="2"`. `init_db()` chạy `ALTER TABLE` thêm `symbols.doc/body/tag`, `files.summary` (guarded). Khi version cũ ≠ 2: **xoá `meta.overview` + reset `files.summary`** (vì overview/summary cũ có thể là hallucination). KHÔNG xoá file/symbol người dùng. `data/` đã backup ngoài (gitignored); có `/api/clear` để rebuild.

## 9.4 Tests + kết quả
Lệnh: `python -m pytest tests -q` → **15 passed**.
- `tests/test_parser.py`: Python (symbol/method/parent/doc/body/edge/import/tag), JS function+arrow+edge, Express route, C#, empty file.
- `tests/test_tagging.py`: regression `Repository` ancestor ≠ be; be segment thật; fe component; event handler; substring không match nhầm.
- `tests/test_retrieval.py`: insufficient evidence; distance threshold; context built + call graph chỉ nội bộ (loại `print`).
- `tests/test_summarizer.py`: lỗi Ollama → `None` (không lưu chuỗi lỗi); OK → trả text.

## 9.5 Kết quả acceptance đã đạt
- **Index chính repo: 1 file/13 symbol → 23 file (22 Python + 1 JS) / 134 symbol**, 0 lỗi.
- **Hỏi `index_project`**: trả đúng chức năng từ source, **cite `codemem/indexer/runner.py`**, **KHÔNG bịa** (openai/mongodb/redis/socket.io/api/project.js/models/project.ts đều = False).
- Query không liên quan → trả "không đủ chứng cứ" (test).
- File đổi → summary/overview cũ bị invalidate.
- Model badge/settings phản ánh model + ctx thật.
- App vẫn chạy lexical khi vector/embedding lỗi (degraded); clear không phụ thuộc load embedding.
- `compileall` + `node --check web/app.js` pass; server import 20 routes.

## 9.6 CHƯA làm — TODO phase sau (ưu tiên giảm dần)
1. **Multi-project schema** (`projects` table + `project_id` mọi bảng/query): hiện vẫn one-project-at-a-time (đổi project vẫn wipe). Đây là acceptance "giữ ≥2 project" **chưa đạt**.
2. **Background jobs** index/summarize có job ID/progress/cancel/retry (hiện index blocking trong request; summarize chạy thread đơn giản).
3. **Lexical FTS5/BM25** thật (hiện token-LIKE). **Token-accurate budget** (hiện xấp xỉ theo ký tự).
4. **Security**: CSRF/Origin/Host + session nonce cho mutation; path allowlist/canonicalize/chống symlink escape; disable `/docs`.
5. **UI overhaul**: sidebar project library, tabs (Chat/Explorer/Routes/Workflows/Issues), responsive 360–1440 + `100dvh`, a11y (`:focus-visible`, aria, semantic button), SSE robust + AbortController, sources click mở snippet, không dùng `alert()`.
6. **Frameworks routes**: FastAPI/Flask/Django/NestJS/Next.js + ASP.NET controller prefix; handler Express lấy đúng handler arg.
7. **Graph**: qualified symbol IDs + provenance; import/inheritance/event graph; coi external/unresolved riêng.
8. **Reconciliation vector** (phát hiện thiếu/thừa/stale embedding) + retry khi DB write OK nhưng Chroma fail.
9. **Chunks rộng hơn**: README/MD, JSON/YAML/TOML, HTML/CSS, SQL ở mức config/chunk; `.gitignore` parsing; thống kê skip reasons.
10. **Overview post-validation** bằng code (loại entity/tech không có trong evidence), không chỉ ở mức prompt; build phân cấp symbol→file→module→project có evidence IDs.
11. **Chat session theo session/project ID** (hiện singleton); persist có giới hạn.

## 9.7 File đã đổi
`codemem/config.py`, `codemem/indexer/{walker,parser,runner,summarizer}.py`, `codemem/storage/{db,vectors}.py`, `codemem/retrieval/search.py`, `codemem/chat/agent.py`, `codemem/api/server.py`, `web/{app.js,index.html}`; thêm `tests/{test_parser,test_tagging,test_retrieval,test_summarizer}.py`; `requirements.txt` (pytest).
