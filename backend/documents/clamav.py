"""A clamd INSTREAM client on the standard library alone (tools/validate.py imports it on a bare checkout).
clamd needs ``AlertExceedsMax yes``, or content past its limits is skipped and answered ``OK``."""
import socket
import struct

CHUNK = 64 * 1024
INSTREAM = b"zINSTREAM\0"


# The EICAR test string is split so no contiguous copy exists in the repository for an on-access scanner to quarantine.
_EICAR_HEAD = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-"
_EICAR_TAIL = rb"ANTIVIRUS-TEST-FILE!$H+H*"


def eicar_bytes():
    return _EICAR_HEAD + _EICAR_TAIL


class ScanError(Exception):
    """Scanner unreachable, timed out or unintelligible: callers must fail closed."""


class InfectedError(Exception):
    def __init__(self, signature):
        self.signature = signature
        super().__init__(signature)


class LimitsExceededError(Exception):
    """clamd declined to inspect the whole file: neither clean nor malware."""

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
        # Heuristics.Limits.Exceeded arrives as FOUND but is not a detection: the file was too big or deep to inspect.
        if signature.startswith("Heuristics.Limits.Exceeded"):
            raise LimitsExceededError(signature)
        raise InfectedError(signature)
    if text.endswith("OK"):
        return None
    raise ScanError(f"unexpected scanner reply: {text!r}")


def scan_stream(fileobj, host, port, timeout=10.0, connect_timeout=3.0, max_bytes=None):
    """Scan an open file: None if clean, raises otherwise. The file is rewound afterwards so the caller can store it."""
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
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"zPING\0")
            return b"PONG" in sock.recv(64)
    except OSError:
        return False
