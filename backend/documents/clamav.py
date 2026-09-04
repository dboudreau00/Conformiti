"""
A clamd client, on the standard library.

Speaks INSTREAM to a ClamAV daemon over TCP: send ``zINSTREAM\\0``, then
length-prefixed chunks, then a zero-length chunk; the daemon answers
``stream: OK`` or ``stream: <signature> FOUND``.

No dependency, because the protocol is a dozen lines and a Python client for it
would be a supply-chain surface for the sake of them. The file is streamed in
64 KiB chunks, so a 32 MB upload never lands in memory.

Three outcomes, and the third matters:

* clean;
* infected — ``InfectedError``, the upload is refused and audited;
* not fully inspected — ``LimitsExceededError``. ClamAV skips content that
  trips ``MaxFileSize`` / ``MaxScanSize`` / ``MaxRecursion`` and, with
  ``AlertExceedsMax yes``, says so. Without that it answers ``OK`` for a file
  it did not actually scan, and the application would store it carrying the
  claim that it was clean.
"""
import socket
import struct

CHUNK = 64 * 1024
INSTREAM = b"zINSTREAM\0"


# The EICAR test string, split so no contiguous copy of it exists in the
# repository for an on-access scanner to quarantine. It lives in this module
# rather than in scanning.py because tools/validate.py imports it on a bare
# checkout, before anything is pip-installed -- and scanning.py needs Django.
_EICAR_HEAD = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-"
_EICAR_TAIL = rb"ANTIVIRUS-TEST-FILE!$H+H*"


def eicar_bytes():
    """The 68-byte EICAR test file, assembled at call time."""
    return _EICAR_HEAD + _EICAR_TAIL


class ScanError(Exception):
    """The scanner could not be reached, timed out, or said something we do
    not understand. Always fail closed on this."""


class InfectedError(Exception):
    def __init__(self, signature):
        self.signature = signature
        super().__init__(signature)


class LimitsExceededError(Exception):
    """ClamAV declined to inspect the whole file. Not the same as clean, and
    not the same as malware."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def parse_response(text):
    """Map a clamd reply to an outcome. Raises, or returns None for clean."""
    text = (text or "").strip()
    if not text:
        raise ScanError("the scanner closed the connection without answering")
    if text.endswith("ERROR"):
        raise ScanError(f"scanner error: {text}")
    if text.endswith("FOUND"):
        signature = text.split(":", 1)[-1].rsplit(" FOUND", 1)[0].strip()
        # Heuristics.Limits.Exceeded is reported as FOUND but is not a
        # detection -- it means the file was too big or too deeply nested to
        # inspect. Refusing it is right; calling it malware is not.
        if signature.startswith("Heuristics.Limits.Exceeded"):
            raise LimitsExceededError(signature)
        raise InfectedError(signature)
    if text.endswith("OK"):
        return None
    raise ScanError(f"unexpected scanner reply: {text!r}")


def scan_stream(fileobj, host, port, timeout=10.0, connect_timeout=3.0, max_bytes=None):
    """Scan an open file. Returns None if clean, raises otherwise.

    The file position is restored on the way out, so callers can hand the same
    handle to storage afterwards.
    """
    try:
        fileobj.seek(0)
    except (AttributeError, OSError):
        pass
    sent = 0
    try:
        with socket.create_connection((host, port), timeout=connect_timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(INSTREAM)
            while True:
                chunk = fileobj.read(CHUNK)
                if not chunk:
                    break
                sent += len(chunk)
                if max_bytes is not None and sent > max_bytes:
                    raise LimitsExceededError(
                        f"file exceeds the {max_bytes} byte scanning limit")
                sock.sendall(struct.pack("!L", len(chunk)) + chunk)
            sock.sendall(struct.pack("!L", 0))
            reply = b""
            while b"\0" not in reply and len(reply) < 4096:
                data = sock.recv(4096)
                if not data:
                    break
                reply += data
    except (LimitsExceededError, InfectedError):
        raise
    except socket.timeout as exc:
        raise ScanError(f"the scanner at {host}:{port} timed out") from exc
    except OSError as exc:
        raise ScanError(f"could not reach the scanner at {host}:{port}: {exc}") from exc
    finally:
        try:
            fileobj.seek(0)
        except (AttributeError, OSError):
            pass

    return parse_response(reply.split(b"\0")[0].decode("utf-8", "replace"))


def ping(host, port, timeout=3.0):
    """True if a clamd answers PING. Used by the boot probe, never per upload."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"zPING\0")
            return b"PONG" in sock.recv(64)
    except OSError:
        return False
