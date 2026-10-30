"""One key file for concurrent workers: written whole, linked into place, and whichever file wins is returned.
Imports only the standard library, because ``settings.py`` imports it."""
import os
import secrets
import time
from pathlib import Path

WAIT_SECONDS = 15
STALE_SECONDS = 60


def _retrying(action):
    """Run ``action``, retrying briefly on PermissionError: Windows reports a sharing violation that way
    while another process reads or replaces the file."""
    for attempt in range(60):
        try:
            return action()
        except PermissionError:
            if attempt == 59:
                raise
            time.sleep(0.05)


def _read(path):
    """The text a file holds, or None when there is no such file."""
    try:
        return _retrying(lambda: Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _unlink(path):
    try:
        os.unlink(str(path))
    except OSError:
        pass


def _link(source, destination):
    """Hard-link ``source`` as ``destination`` (an exclusive create where links fail):
    True when this process took the name."""
    try:
        os.link(str(source), str(destination))
        return True
    except FileExistsError:
        return False
    except OSError:
        pass
    try:
        fd = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(Path(source).read_text(encoding="utf-8"))
    return True


#: Windows raises PermissionError, not FileExistsError, for a name whose file is still being deleted.
DELETE_PENDING_REFUSED = os.name == "nt"


def _take(claim):
    try:
        os.close(os.open(str(claim), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        return True
    except FileExistsError:
        return False
    except PermissionError:
        # Windows: the name is still held for a moment. Elsewhere the directory is unwritable, which is a real error.
        if DELETE_PENDING_REFUSED:
            return False
        raise


def _age(path):
    try:
        return time.time() - os.stat(str(path)).st_mtime
    except OSError:
        return 0


def publish(path, text):
    """Make ``path`` hold ``text`` unless a key is there; return what the file holds, which may be another process's.
    Only an empty file counts as no key. Raises OSError where the filesystem will not do it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        return _place(path, tmp, text)
    finally:
        _unlink(tmp)


def _place(path, tmp, text):
    claim = path.with_name(f".{path.name}.fill")
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        current = _read(path)
        if current is not None and current.strip():
            return current
        if current is None:
            if _link(tmp, path):
                return text
            continue                             # lost the race: read the winner's
        if _take(claim):
            try:
                # Re-read under the claim: the previous holder may have filled the file since the loop read it.
                current = _read(path)
                if current is not None and current.strip():
                    return current
                _retrying(lambda: os.replace(str(tmp), str(path)))
                return text
            finally:
                _unlink(claim)
        if _age(claim) > STALE_SECONDS:
            _unlink(claim)
            continue
        if time.monotonic() > deadline:
            raise OSError(f"another process is filling the empty key file {path} and did not "
                          f"finish; remove {claim} if no process is running")
        time.sleep(0.05)
