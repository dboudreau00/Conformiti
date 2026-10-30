"""EMAIL_PROVIDER=mailbox: sends over SMTP; IMAP and POP3 only verify the account and, for IMAP, file a copy in Sent.
Standard library only."""
import imaplib
import logging
import poplib
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from django.conf import settings

logger = logging.getLogger(__name__)


def build_message(subject, html_body, text_body, from_address, to_addresses):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = ", ".join(to_addresses)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=_domain_of(from_address))
    msg.set_content(text_body or "")
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    return msg


def _domain_of(address):
    return address.split("@")[-1] if address and "@" in address else "localhost"


def _smtp_conf():
    return {
        "host": settings.MAILBOX_SMTP_HOST or settings.MAILBOX_HOST,
        "port": settings.MAILBOX_SMTP_PORT,
        "username": settings.MAILBOX_SMTP_USERNAME or settings.MAILBOX_USERNAME,
        "password": settings.MAILBOX_SMTP_PASSWORD or settings.MAILBOX_PASSWORD,
        "use_ssl": settings.MAILBOX_SMTP_USE_SSL,
        "use_tls": settings.MAILBOX_SMTP_USE_TLS,
        "timeout": settings.MAILBOX_TIMEOUT,
    }


def send_mailbox_email(subject, html_body, text_body, to_addresses, from_address=None):
    from_address = from_address or settings.DEFAULT_FROM_EMAIL
    to_addresses = [a for a in dict.fromkeys(to_addresses) if a]
    if not to_addresses:
        return False

    msg = build_message(subject, html_body, text_body, from_address, to_addresses)
    conf = _smtp_conf()

    if conf["use_ssl"]:
        context = ssl.create_default_context()
        server = smtplib.SMTP_SSL(conf["host"], conf["port"], timeout=conf["timeout"], context=context)
    else:
        server = smtplib.SMTP(conf["host"], conf["port"], timeout=conf["timeout"])
    try:
        server.ehlo()
        if conf["use_tls"] and not conf["use_ssl"]:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if conf["username"]:
            server.login(conf["username"], conf["password"])
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            logger.debug("mailbox: closing the connection failed", exc_info=True)

    if settings.MAILBOX_SAVE_SENT and settings.MAILBOX_PROTOCOL == "imap":
        try:
            append_to_sent(msg)
        except Exception:
            # Best-effort, since delivery already succeeded; logged because operators rely on the Sent copy as the audit
            # record and a failing folder would otherwise look like a working one.
            logger.warning(
                "Reminder delivered but could not be filed in the '%s' IMAP folder.",
                settings.MAILBOX_SENT_FOLDER or "Sent", exc_info=True,
            )
    return True


def _tls_context():
    """A verifying context: imaplib and poplib default to an unverified one, which would hand the mailbox password
    to anyone who presents any certificate."""
    return ssl.create_default_context()


def _imap_connect():
    timeout = settings.MAILBOX_TIMEOUT
    if settings.MAILBOX_USE_SSL:
        conn = imaplib.IMAP4_SSL(
            settings.MAILBOX_HOST, settings.MAILBOX_PORT,
            ssl_context=_tls_context(), timeout=timeout,
        )
    else:
        conn = imaplib.IMAP4(settings.MAILBOX_HOST, settings.MAILBOX_PORT, timeout=timeout)
        try:
            conn.starttls(ssl_context=_tls_context())
        except Exception:
            logger.warning(
                "IMAP server %s does not support STARTTLS; credentials would be "
                "sent unencrypted.", settings.MAILBOX_HOST,
            )
            raise
    conn.login(settings.MAILBOX_USERNAME, settings.MAILBOX_PASSWORD)
    return conn


def _pop3_connect():
    timeout = settings.MAILBOX_TIMEOUT
    if settings.MAILBOX_USE_SSL:
        conn = poplib.POP3_SSL(
            settings.MAILBOX_HOST, settings.MAILBOX_PORT,
            context=_tls_context(), timeout=timeout,
        )
    else:
        conn = poplib.POP3(settings.MAILBOX_HOST, settings.MAILBOX_PORT, timeout=timeout)
        try:
            conn.stls(context=_tls_context())
        except Exception:
            logger.warning(
                "POP3 server %s does not support STLS; credentials would be "
                "sent unencrypted.", settings.MAILBOX_HOST,
            )
            raise
    conn.user(settings.MAILBOX_USERNAME)
    conn.pass_(settings.MAILBOX_PASSWORD)
    return conn


def append_to_sent(msg):
    conn = _imap_connect()
    try:
        folder = settings.MAILBOX_SENT_FOLDER or "Sent"
        # imaplib does not quote the mailbox argument, so a folder with a space ("Sent Items", "[Gmail]/Sent Mail")
        # is parsed as extra tokens and the APPEND fails.
        conn.append(
            f'"{folder}"' if not folder.startswith('"') else folder,
            r"(\Seen)",
            imaplib.Time2Internaldate(time.time()),
            msg.as_bytes(),
        )
    finally:
        try:
            conn.logout()
        except Exception:
            logger.debug("mailbox: closing the connection failed", exc_info=True)


def verify_mailbox():
    """Sign in over IMAP or POP3 and return a one-line status; raises on failure."""
    protocol = settings.MAILBOX_PROTOCOL
    if protocol == "imap":
        conn = _imap_connect()
        try:
            _, data = conn.list()
            boxes = len(data) if data else 0
            return f"IMAP OK ({settings.MAILBOX_HOST}:{settings.MAILBOX_PORT}): {boxes} mailboxes visible"
        finally:
            try:
                conn.logout()
            except Exception:
                logger.debug("mailbox: closing the connection failed", exc_info=True)
    elif protocol == "pop3":
        conn = _pop3_connect()
        try:
            count, size = conn.stat()
            return f"POP3 OK ({settings.MAILBOX_HOST}:{settings.MAILBOX_PORT}): {count} messages, {size} bytes"
        finally:
            try:
                conn.quit()
            except Exception:
                logger.debug("mailbox: closing the connection failed", exc_info=True)
    raise ValueError(f"Unknown MAILBOX_PROTOCOL: {protocol!r} (expected 'imap' or 'pop3')")
