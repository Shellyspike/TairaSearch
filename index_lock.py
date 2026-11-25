"""Interprocess writer lock for one SQLite index."""

import errno
import os
from contextlib import contextmanager
from pathlib import Path


def index_lock_path(db_path: Path) -> Path:
    db_path = db_path.expanduser().resolve()
    return db_path.with_name(f"{db_path.name}.writer.lock")


@contextmanager
def index_writer_lock(db_path: Path):
    """Fail fast on contention; closing the handle releases the OS lock."""
    lock_path = index_lock_path(db_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if not isinstance(exc, BlockingIOError) and not (
                os.name == "nt" and exc.errno == errno.EACCES
            ):
                raise
            raise RuntimeError(
                f"Индекс занят другой операцией записи: {db_path}. "
                "Дождитесь завершения индексации или очистки и повторите команду."
            ) from exc
        yield
