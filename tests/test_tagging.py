"""Regression: tag FE/BE phai dung RELATIVE path + khop segment, khong substring."""
from codemem.indexer.parser import _compute_tag


def test_repository_ancestor_not_be():
    # rel path (da loai thu muc to tien 'Repository') -> web/app.js KHONG duoc thanh 'be'
    assert _compute_tag("web/app.js", "javascript", "function", "render") != "be"


def test_real_be_segment():
    assert _compute_tag("src/services/pay.js", "javascript", "function", "charge") == "be"


def test_fe_component():
    assert _compute_tag("src/components/Btn.tsx", "tsx", "function", "Btn") == "fe"


def test_event_handler():
    assert _compute_tag("src/ui/x.js", "javascript", "function", "onClick") == "event"


def test_substring_not_matched():
    # 'repository' la substring cua mot ten thu muc khac -> khong duoc match nham
    assert _compute_tag("myrepositoryx/app.js", "javascript", "function", "render") != "be"
