"""Create a key file that every process booting at once agrees on.

Workers start together, and each of them reads the key file before it has been
written. A key is therefore written whole to a private temporary name and linked
into place: nobody reads a half-written file, and two processes cannot each keep
a key of their own, because the one that loses the link reads the winner's.

A file that is there but empty (an operator's ``touch``, or the last crash of a
release that wrote the name first) is filled the same way, under a claim only
one process can take. The others wait for the file to fill and read what it
holds. A claim older than :data:`STALE_SECONDS` was left by a process that died,
and is cleared once.

This module imports nothing but the standard library: ``settings.py`` imports it.
"""
import os
import secrets
import time
from pathlib import Path

#: How long a process waits for another to finish filling an empty file.
WAIT_SECONDS = 15
#: A claim older than this was left behind by a process that died holding it.
STALE_SECONDS = 60


def _retrying(action):
    """Run ``action``, trying again for a moment when Windows reports a sharing
    violation as PermissionError: a file that another process is reading cannot
    be replaced, and one that is being replaced cannot be read, for the few
    milliseconds that takes. Anywhere else the first attempt is the only one."""
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
    """Give ``source``'s content the name ``destination`` if nobody has taken it:
    True when this process did, False when the name was already there. A
    filesystem without hard links gets an exclusive create instead."""
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


def _take(claim):
    """Take the claim on filling an empty key file, or say it is held."""
    try:
        os.close(os.open(str(claim), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        return True
    except FileExistsError:
        return False


def _age(path):
    try:
        return time.time() - os.stat(str(path)).st_mtime
    except OSError:
        return 0


def publish(path, text):
    """Make ``path`` hold ``text`` unless a key is there already, and return what
    the file holds once this has run: ``text`` when this process created it, the
    other process's when it got there first. Only an empty file counts as no
    key. Raises OSError for a filesystem that will not do it."""
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
            return current                       # a key is there: it wins
        if current is None:
            if _link(tmp, path):
                return text
            continue                             # lost the race: read the winner's
        # An empty file. One process fills it; the rest wait and read.
        if _take(claim):
            try:
                # Asked again under the claim: the process that held it before
                # us may have filled the file and let go since this loop read it.
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
