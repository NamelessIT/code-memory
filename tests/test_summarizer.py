"""Summarizer grounding: KHONG luu chuoi loi lam summary."""
import codemem.indexer.summarizer as sm


class _Raise:
    def chat(self, *a, **k):
        raise RuntimeError("ollama down")


class _Ok:
    def chat(self, *a, **k):
        return {"message": {"content": "Tom tat hop le."}}


def test_ask_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(sm, "_client", _Raise())
    assert sm.summarize_file("FILE: x\nSYMBOLS:") is None   # khong tra chuoi loi


def test_ask_returns_text_when_ok(monkeypatch):
    monkeypatch.setattr(sm, "_client", _Ok())
    out = sm.summarize_file("FILE: x")
    assert out == "Tom tat hop le."
