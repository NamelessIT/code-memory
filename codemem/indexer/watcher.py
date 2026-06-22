"""Auto re-index: theo doi project_root, file doi -> index lai (debounce)."""
import threading
from pathlib import Path

from ..config import IGNORE_DIRS
from ..storage import db
from .walker import detect_lang
from .runner import index_single_file, remove_file, INDEX_LOCK

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    _HAS_WATCHDOG = True
except ImportError:
    _HAS_WATCHDOG = False
    FileSystemEventHandler = object


def _ignored(path: str) -> bool:
    parts = Path(path).parts
    return any(p.lower() in IGNORE_DIRS for p in parts)   # khong phan biet hoa/thuong


def _relevant(path):
    return (not _ignored(path)) and detect_lang(Path(path)) is not None


class _Handler(FileSystemEventHandler):
    def __init__(self, manager):
        self.m = manager

    def on_moved(self, event):
        # File doi cho: go src cu, index dest moi
        if event.is_directory:
            return
        if _relevant(event.src_path):
            self.m.schedule(event.src_path, deleted=True)
        if _relevant(event.dest_path):
            self.m.schedule(event.dest_path, deleted=False)

    def on_any_event(self, event):
        if event.is_directory or event.event_type == "moved":
            return
        path = event.src_path
        if not _relevant(path):
            return
        self.m.schedule(path, deleted=(event.event_type == "deleted"))


class WatcherManager:
    """Quan ly 1 observer; debounce; BIND project_id + generation tai luc start (#P0-6)."""
    def __init__(self):
        self.observer = None
        self.root = None
        self.project_id = None
        self.generation = 0          # tang moi lan start/stop -> phat hien timer/flush stale
        self._pending = {}
        self._lock = threading.Lock()
        self._timer = None

    def start(self, root: str, project_id=None):
        if not _HAS_WATCHDOG:
            return False
        self.stop()
        with self._lock:
            self.generation += 1
            self.root = str(Path(root).resolve())
            self.project_id = project_id
        self.observer = Observer()
        self.observer.schedule(_Handler(self), self.root, recursive=True)
        self.observer.daemon = True
        self.observer.start()
        return True

    def stop(self):
        with self._lock:
            self.generation += 1     # vo hieu hoa moi timer/flush dang cho
            if self._timer:
                self._timer.cancel()
                self._timer = None
            self._pending.clear()
            self.project_id = None
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=2)
            except Exception:
                pass
            self.observer = None
        self.root = None

    def schedule(self, path, deleted=False):
        with self._lock:
            gen = self.generation
            self._pending[path] = deleted
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(1.5, self._flush, args=(gen,))
            self._timer.daemon = True
            self._timer.start()

    def _flush(self, gen):
        with self._lock:
            if gen != self.generation:   # timer stale (da switch/stop) -> CHI bo phan cua minh.
                return                    # KHONG clear _pending: do la pending cua generation hien tai
            pid = self.project_id
            pending = dict(self._pending)
            self._pending.clear()
        # Lay INDEX_LOCK roi RE-CHECK generation + project ton tai TRUOC moi write (#P0-6):
        # giua luc copy pending va luc ghi co the da stop/switch/delete (op do giu INDEX_LOCK). Neu
        # khong re-check, callback cu se re-tao file/vector cho project da doi/xoa.
        with INDEX_LOCK:
            if gen != self.generation or pid is None or not db.project_exists(pid):
                return                   # stale: bo, khong ghi
            for path, deleted in pending.items():
                try:
                    if deleted:
                        remove_file(path, project_id=pid)
                    else:
                        index_single_file(path, project_id=pid)
                except Exception as e:
                    print(f"[warn] watcher flush {path}: {e}")


manager = WatcherManager()
