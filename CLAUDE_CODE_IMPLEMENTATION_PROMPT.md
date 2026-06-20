# Prompt tiếp theo cho Claude Code — chỉ còn các vấn đề chưa hoàn thành

Hãy đọc code hiện tại trước khi sửa. Hai commit gần nhất đã có Python indexing, evidence body/doc cơ bản, grounded retrieval bước đầu và multi-project cơ bản. Không làm lại các phần đó nếu không cần cho migration/fix; tập trung hoàn thành những mục còn thiếu và các regression dưới đây.

Không chỉ viết kế hoạch: hãy sửa code, thêm migration/tests, chạy app thật và chứng minh acceptance criteria. Không append báo cáo triển khai vào file này; báo cáo trong chat hoặc file riêng.

## P0 — regression/correctness phải sửa trước

### 1. Overview per-project đang hỏng ở API

- Summarizer lưu overview bằng db.set_overview() vào key overview:{project_id}.
- codemem/api/server.py:101-103 vẫn đọc db.get_meta("overview"), nên nút Tổng quan trả rỗng.
- Sửa endpoint dùng db.get_overview(project_id) và thêm API test cho hai project có overview khác nhau.

### 2. Endpoint /api/file đang gọi hàm không tồn tại

- codemem/api/server.py:142-147 gọi db.get_symbols_for_files([path]).
- Hàm này không còn trong codemem/storage/db.py, nên endpoint sẽ 500.
- Khôi phục API project-scoped bằng file ID/path + project ID; không cho đọc file thuộc project khác.

### 3. Overview stale khi source thay đổi

- db.upsert_file() xóa summary của file nhưng không invalidate overview:{project_id}.
- Watcher/index incremental vì vậy vẫn đưa overview cũ vào context cho tới lần summarize tiếp theo.
- Khi file add/update/delete, đánh dấu/xóa overview và các derived facts liên quan. Thêm regression test.

### 4. Lexical-only/degraded mode chưa an toàn như báo cáo cũ

- vectors.get_collection() chỉ catch ImportError. Lỗi load SentenceTransformer, model cache, Hugging Face/network, Chroma schema hoặc corrupt index vẫn propagate.
- vectors.query/index_file/delete_file/delete_project/available gọi get_collection() ngoài vùng catch phù hợp.
- vectors.clear_all() còn khởi tạo/load embedding chỉ để clear và vẫn nuốt mọi exception.
- Yêu cầu: mọi thao tác vẫn chạy lexical-only khi vector unavailable; health trả nguyên nhân degraded; clear/delete không cần load embedding; lỗi không bị nuốt.

### 5. SQLite thành công nhưng vector thất bại làm index vĩnh viễn thiếu

- runner.index_project() commit db.upsert_file() trước vectors.index_file().
- Nếu vector add lỗi, hash SQLite đã mới nên lần index sau file bị skip.
- Thêm trạng thái embedding/version per file hoặc outbox/reconciliation idempotent. Lần sau phải tự retry vector thiếu/stale.

### 6. Race giữa watcher và chuyển/index project

- /api/index không stop watcher project cũ trước khi index_project() đổi active project.
- Event project A có thể chạy sau khi active đã thành B; index_single_file() dùng active project toàn cục và ghi file A vào B.
- WatcherManager.stop() không cancel timer/clear pending; timer cũ có thể flush sau switch.
- _ignored() trong watcher vẫn phân biệt hoa/thường dù walker đã sửa.
- Xử lý moved event (src_path + dest_path), serialize index/watch/delete và log lỗi thay vì except: pass.

### 7. Summarizer có thể trộn project khi người dùng switch

- run_summarize() capture pid, nhưng nhiều DB call và build_overview() lại dùng active project tại thời điểm gọi.
- Progress cũng là singleton global.
- Job phải bind cứng project_id từ đầu đến cuối; switch UI không đổi target job. Overview, summaries và vector metadata phải cùng project.

### 8. Multi-project schema chưa cô lập được project lồng nhau

- files.path vẫn là PRIMARY KEY toàn cục; vector IDs cũng chỉ dựa trên absolute path.
- Nếu project B nằm trong project A, cùng file được index ở cả hai thì B sẽ overwrite/steal file/symbol của A.
- Đã tái hiện: index C:/repo/sub/x.py cho A rồi B làm A từ 1 file xuống 0.
- Migration sang stable file_id và uniqueness (project_id, relative_path) hoặc tương đương. Symbol/edge/route/chunk/vector ID phải chứa project ID.
- Canonicalize root theo Windows (case/drive/separator) để cùng thư mục không tạo hai project.

### 9. Project ID không được validate

- set_active_project(999999) hiện ghi ID không tồn tại; API vẫn trả ok: true, active project thành None.
- Select/delete phải 404 cho project không tồn tại.
- Khi xóa active project, tự chọn project hợp lệ kế tiếp hoặc hiển thị trạng thái trống nhất quán. Hiện dropdown có thể nhìn như đã chọn project đầu tiên nhưng backend không có active project.

### 10. Xóa/switch project và clear phải nhất quán

- Vector delete có thể fail sau khi SQLite đã xóa, để orphan embeddings.
- Clear toàn bộ hiện giữ chat history dù evidence/project đã mất.
- Mutation cần result rõ (success/partial/retry), reconciliation và reset/bind session đúng project.

## P1 — memory/retrieval còn thiếu

### 11. Lexical retrieval và ranking

- Thay token-LIKE bằng SQLite FTS5/BM25 hoặc lexical index tương đương.
- Tokenizer hiện chỉ nhận ASCII identifier dài từ 3 ký tự, yếu với tiếng Việt và symbol ngắn.
- Kết hợp exact symbol/file/route lookup → lexical → semantic, có score threshold được hiệu chỉnh bằng fixture thật.
- Không dùng set iteration làm ranking nondeterministic.
- Có diversity theo file/module và trả “không đủ chứng cứ” cho query không liên quan.

### 12. Context budget phải token-aware

- CONTEXT_CHAR_BUDGET và MAX_HISTORY_CHARS vẫn dựa ký tự.
- Tính tổng budget gồm system + evidence + overview + brain + history + user + output reserve.
- Hỗ trợ ít nhất context 8192 và 32768; không vượt budget và không nhồi đầy model nhỏ.
- Không để một skeleton quá lớn gây break và loại mọi file sau.
- Sources phải chứa mọi file thực sự xuất hiện trong symbol/evidence/context; hiện chỉ thêm file có skeleton vừa budget.

### 13. Stable symbol graph + provenance

- Call graph vẫn dùng simple name và symbol_exists(name). External call trùng tên internal vẫn bị coi là internal; method cùng tên ở class/file khác bị gộp.
- Thêm stable symbol ID/qualified name, resolved/unresolved/external target, confidence và file/line provenance.
- Bổ sung import/dependency, inheritance/implements, contains, event emit/listen/producer/consumer.

### 14. Mở rộng coverage codebase

- Thêm chunk/config indexing cho README/Markdown, JSON/YAML/TOML, HTML/CSS, SQL.
- Tôn trọng .gitignore; báo file skip + reason thay vì bỏ âm thầm.
- Thêm route extractors tối thiểu cho FastAPI (chính repo hiện có 0 route), Flask/Django, NestJS/Next.js và ASP.NET controller prefix.
- Express route phải resolve đúng handler argument/middleware.
- Thêm workflow/entrypoint/architecture/security/config facts có evidence file+line.

### 15. Summary/overview cần validation bằng code

- Prompt “không bịa” chưa đủ.
- Overview vẫn dùng basename, giới hạn 400 file và cắt body ở 8000 ký tự âm thầm; dễ trùng file/mất module.
- Build phân cấp symbol → file → module → project, lưu source hash/prompt version/model/provenance.
- Reject hoặc đánh dấu unsupported entity/technology không có trong evidence.
- Summary nên dùng doc/body/chunks phù hợp, không chỉ skeleton.

## P1 — API, lifecycle và security

### 16. Background jobs

- Index vẫn blocking trong request; summarize chỉ là daemon thread + progress global.
- Thêm job ID, project ID, phase/current file, warnings/errors, cancel/retry và conflict policy.
- App restart phải biết job interrupted; không có hai job ghi cùng project.

### 17. Session/project scoping

- session = ChatSession() và active project vẫn singleton toàn server.
- Hai tab có thể switch project/reset history của nhau; retrieval đọc active project nhiều lần trong một query nên có thể trộn project khi concurrent switch.
- Mỗi request/chat session phải mang project_id cố định; pass nó xuyên suốt DB/vector/retrieval/summarizer/watcher.
- Persist history có giới hạn hoặc ít nhất tách theo session + project.

### 18. Security boundary cho local API

- Thêm Origin/Host validation + session nonce/CSRF token cho mutation.
- Validate body/message/query length.
- Canonicalize/allowlist folder người dùng đã chủ động thêm; mặc định không follow symlink ra ngoài root.
- Nếu bind khác localhost thì yêu cầu auth rõ ràng.
- Disable /docs mặc định ở chế độ packaged hoặc có setting.
- Không trả raw internal exception/path ngoài mức cần thiết.

### 19. Lifespan, health và logging

- Dùng FastAPI lifespan để startup/shutdown watcher/job/DB sạch.
- Health riêng cho SQLite, vector/embedding, Ollama, watcher và active project.
- Structured log có request/job/project ID.
- Xóa các except Exception: pass ở critical path; lỗi phải observable và retryable.

## P1/P2 — model/runtime/setup

### 20. Model và context 33k chưa được tự phát hiện/chọn trong UI

- Config đã đọc env nhưng default vẫn agent-7b-v2 + 8192.
- /api/models chỉ liệt kê tên, chưa đọc context capability; UI không có model/settings picker.
- Đọc Ollama capabilities, cho chọn model đã cài, context/budget/embedding/brain; persist settings local.
- Không tự nhận là Qwen 2B nếu model thực tế khác. Cảnh báo model missing/context mismatch.

### 21. Cài đặt vẫn phụ thuộc máy tác giả

- scripts/start.bat vẫn fallback vào C:\Agent\Agent_Ollama\Ollama\.venv.
- Requirements dùng range rộng, chưa lock/constraints; pytest nằm chung runtime deps; venv hiện tại có uv shim nhưng không có pip.
- Thêm bootstrap/check script Windows, Python version support, dependency lock/constraints và dev extras.
- Không tự download embedding/model lớn trong startup/clear.
- Thêm .pytest_cache/ vào .gitignore; dọn cache không tạo ACL làm Git báo permission denied.

### 22. README đang stale/mâu thuẫn

- Đầu README vẫn ghi chỉ JS/TS/TSX/C#, dù feature bên dưới có Python.
- Vẫn ghi “tự dọn khi đổi project”, trái với multi-project preservation.
- Roadmap đánh dấu hoàn tất dù còn nhiều mục.
- Cập nhật kiến trúc, migration, config, degraded mode, project lifecycle và lệnh test đúng.

## P1/P2 — UI/UX/accessibility

### 23. UI mới chỉ thêm dropdown project

- Cần project sidebar/drawer với fresh/stale/indexing/error/last indexed.
- Tabs/panels: Chat, Explorer, Routes, Workflows/Architecture, Issues/Index log.
- Source chip click mở evidence snippet + relative path/line/score/reason.
- Routes/structure có filter và không truncate âm thầm.
- Hiển thị model/context thật, Ollama/embedding/watcher health và token usage.

### 24. Streaming và error handling

- Kiểm tra response.ok; parser SSE xử lý CRLF, nhiều data line, malformed event và final buffer.
- AbortController + Stop generation, retry/copy.
- Loading indicator khi chưa có token.
- Poll summarize có timeout/error handling; báo partial success thay vì luôn “thành công”.
- Không dùng alert() cho luồng chính; dùng inline error/toast.

### 25. Responsive và accessibility

- Dùng 100dvh, min-width:0, media queries cho 360/768/1024/1440.
- Semantic button thay các example span; aria-label, keyboard navigation, :focus-visible.
- Tooltip dùng được bằng focus; prefers-reduced-motion.
- Sanitize Markdown, không bật raw HTML.
- Render/test thật desktop và mobile, xác nhận không horizontal overflow.

## Tests bắt buộc bổ sung

Suite hiện có 17 unit tests nhưng chưa test API/lifecycle/UI và chưa bắt các regression P0 ở trên. Bổ sung ít nhất:

1. /api/overview per-project và /api/file không 500/không leak project.
2. Nested/overlapping projects không overwrite file/vector.
3. Invalid project ID → 404; delete active chọn fallback nhất quán.
4. File add/update/delete invalidate summary + overview đúng project.
5. Switch project trong lúc watcher debounce/summarizer/index job không trộn dữ liệu.
6. Embedding init/query/add/delete/clear lần lượt fail → lexical mode vẫn chạy và reconciliation retry được.
7. DB commit OK + vector fail → lần index sau không skip vector repair.
8. Duplicate symbol names/external call collision không làm graph sai.
9. Vietnamese query, exact symbol, unrelated query và threshold trên fixture embedding deterministic.
10. Token budget ở 8192/32768; source citations khớp evidence.
11. FastAPI/Express/ASP.NET route fixtures và metadata/config chunks.
12. CSRF/origin/nonce, symlink escape, input limits, session/project isolation.
13. UI smoke desktop/mobile, keyboard, stream abort, source drawer, job progress/error.
14. Migration từ schema v2/v3 và rollback/backup.

Chạy fresh:

    python -m pytest tests -q
    python -m compileall -q codemem
    node --check web/app.js

Trong lượt review này, việc chạy lại pytest qua uv-shim của venv bị treo không tạo process Python; đừng dùng báo cáo “17 passed” cũ làm bằng chứng cuối. Hãy chạy bằng môi trường sạch và ghi rõ Python/dependency versions.

## Acceptance criteria còn lại

- Hai project độc lập, kể cả root lồng nhau, không leak/overwrite SQLite hoặc vector.
- Mọi API hiện hữu có integration test; /api/overview và /api/file hoạt động.
- Watcher/summarizer/index/chat bind project ID cố định và an toàn khi concurrent switch/delete.
- Source đổi không để summary/overview/vector stale.
- Vector/embedding/Ollama down không làm lexical index/search/clear/delete crash.
- Hỏi về architecture chính repo tìm thấy FastAPI routes và evidence từ Python + metadata; không bịa technology.
- Query không liên quan trả insufficient evidence; citation luôn trỏ evidence thực sự đã đưa vào context.
- Model/context UI phản ánh capability Ollama thật và hỗ trợ cấu hình khoảng 32–33k.
- Security checks cho mutation/path/session pass.
- UI responsive/accessibility/stream abort/source explorer được render-test thật.
- README/setup/migration đúng với hành vi hiện tại.
- Toàn bộ tests pass trong môi trường tái tạo được; không còn critical exception bị nuốt.
