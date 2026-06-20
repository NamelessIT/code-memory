"""Auto re-index: theo doi project_root, file doi -> index lai (debounce)."""
import threading
from pathlib import Path

from ..config import IGNORE_DIRS
from .walker import detect_lang
from .runner import index_single_file, remove_file

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
    """Quan ly 1 observer; debounce cac thay doi roi index lai."""
    def __init__(self):
        self.observer = None
        self.root = None
        self._pending = {}      # path -> deleted?
        self._lock = threading.Lock()
        self._timer = None

    def start(self, root: str):
        if not _HAS_WATCHDOG:
            return False
        self.stop()
        self.root = str(Path(root).resolve())
        self.observer = Observer()
        self.observer.schedule(_Handler(self), self.root, recursive=True)
        self.observer.daemon = True
        self.observer.start()
        return True

    def stop(self):
        # Huy timer + clear pending de event project cu khong flush sau khi switch
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            self._pending.clear()
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
            self._pending[path] = deleted
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(1.5, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self):
        with self._lock:
            pending = dict(self._pending)
            self._pending.clear()
        for path, deleted in pending.items():
            try:
                if deleted:
                    remove_file(path)
                else:
                    index_single_file(path)
            except Exception:
                pass


manager = WatcherManager()
