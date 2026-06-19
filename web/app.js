const $ = (id) => document.getElementById(id);
const chat = $("chat");

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Render markdown toi gian: code block ```...``` va inline `code`
function renderMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
    `<pre><code>${code.replace(/\n$/, "")}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  return html;
}

function addMsg(role) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  wrap.innerHTML = `<div class="role">${role === "user" ? "Bạn" : "code-memory"}</div>
                    <div class="bubble"></div>`;
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
  return wrap.querySelector(".bubble");
}

async function loadStatus() {
  try {
    const r = await fetch("/api/status");
    const s = await r.json();
    const proj = s.project_root ? ` | ${s.project_root}` : " | chưa index project nào";
    $("status").textContent = `${s.files} file · ${s.symbols} symbol${proj}`;
  } catch {
    $("status").textContent = "Không kết nối được server";
  }
}

async function indexProject() {
  const path = $("projectPath").value.trim();
  if (!path) return;
  $("indexBtn").disabled = true;
  $("indexBtn").textContent = "Đang index...";
  try {
    const r = await fetch("/api/index", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    const res = await r.json();
    if (res.error) {
      alert(res.error);
    } else {
      const b = addMsg("assistant");
      b.textContent = `✅ Đã index: +${res.new} mới, ${res.updated} cập nhật, ${res.skipped} bỏ qua, ${res.removed} gỡ, ${res.errors} lỗi.`;
    }
  } catch (e) {
    alert("Lỗi index: " + e);
  } finally {
    $("indexBtn").disabled = false;
    $("indexBtn").textContent = "Index";
    loadStatus();
  }
}

async function send() {
  const input = $("input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  input.style.height = "auto";

  addMsg("user").textContent = message;
  const bubble = addMsg("assistant");
  let sources = [];
  let reply = "";

  $("sendBtn").disabled = true;
  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const part of parts) {
        const line = part.replace(/^data: /, "").trim();
        if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.type === "sources") {
          sources = ev.sources || [];
        } else if (ev.type === "token") {
          reply += ev.text;
          bubble.innerHTML = renderMarkdown(reply);
          chat.scrollTop = chat.scrollHeight;
        } else if (ev.type === "error") {
          bubble.innerHTML = `<span style="color:#f38ba8">${escapeHtml(ev.text)}</span>`;
        }
      }
    }
    if (sources.length) {
      const div = document.createElement("div");
      div.className = "sources";
      div.innerHTML = "<b>Nguồn:</b> " + sources.map(escapeHtml).join("<br>");
      bubble.parentElement.appendChild(div);
    }
  } catch (e) {
    bubble.innerHTML = `<span style="color:#f38ba8">Lỗi: ${escapeHtml(String(e))}</span>`;
  } finally {
    $("sendBtn").disabled = false;
    chat.scrollTop = chat.scrollHeight;
  }
}

async function resetChat() {
  await fetch("/api/reset", { method: "POST" });
  chat.innerHTML = "";
}

async function clearIndex() {
  if (!confirm("Xoá toàn bộ index codebase (SQLite + vector)? Lịch sử chat giữ nguyên.")) return;
  await fetch("/api/clear", { method: "POST" });
  addMsg("assistant").textContent = "🗑️ Đã xoá toàn bộ index. Index lại project khi cần.";
  loadStatus();
}

$("sendBtn").onclick = send;
$("indexBtn").onclick = indexProject;
$("clearBtn").onclick = clearIndex;
$("resetBtn").onclick = resetChat;
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
$("input").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 160) + "px";
});

loadStatus();
