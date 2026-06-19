"""Cau noi toi brain cua agent goc (~/.agent-brain) de lay bai hoc lien quan."""
import sys

from ..config import BRAIN_DIR, USE_BRAIN, BRAIN_LESSONS_K

_brain = None
_failed = False


def _get_brain():
    """Lazy import module brain.py tu ~/.agent-brain."""
    global _brain, _failed
    if _brain is None and not _failed:
        try:
            sys.path.insert(0, str(BRAIN_DIR))
            import brain  # noqa
            _brain = brain
        except Exception:
            _failed = True
    return _brain


def lessons_for(query: str) -> str:
    """Tra ve text bai hoc lien quan tu brain (rong neu tat/khong co)."""
    if not USE_BRAIN:
        return ""
    b = _get_brain()
    if b is None:
        return ""
    try:
        rows = b.search_similar(query, n=BRAIN_LESSONS_K)
    except Exception:
        return ""
    if not rows:
        return ""
    # row: id,ts,project,language,category,title,description,bad_code,good_code,...
    lines = []
    for r in rows:
        title = r[5]
        desc = (r[6] or "")[:280]
        lines.append(f"- {title}: {desc}")
    return "\n".join(lines)
