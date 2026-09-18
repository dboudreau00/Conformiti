"""Proving an account is yours, again, in the middle of a session.

Enrolling or removing a factor is the moment a hijacked session becomes a
permanent one: the attacker adds their own authenticator, or takes yours away,
and the account is theirs after the stolen cookie expires. Every one of those
four operations asks for proof here.
"""


def reauthenticated(request):
    """Has the caller just proved the account is theirs?

    Adding a passkey used to take nothing, so a hijacked session could quietly
    enrol the attacker's own key and keep the account for good. Enrolling an
    authenticator app was the same gap, and it was worse: the attacker's app
    became the second factor the real owner then had to produce (0.9.5f).
    All four operations now ask for the same proof -- the password, or a code
    from a factor already enrolled, which is what an account signed in through
    an identity provider has instead of a password. A backup code counts:
    removal used to insist on a password, which an SSO account does not have,
    so the owner of a passkey reported cloned could not take it off.

    An account with neither (no usable password, no second factor) has
    nothing to prove with and nothing yet to protect: that is the first
    enrolment, and it is allowed.
    """
    user = request.user
    password = request.data.get("password") or ""
    otp = str(request.data.get("otp") or "").strip()
    has_password = user.has_usable_password()
    if has_password and password and user.check_password(password):
        return True
    if otp and user.mfa_enabled:
        device = getattr(user, "mfa_device", None)
        if device is not None and device.enabled and device.verify(otp):
            return True
        if user.verify_backup_code(otp):
            return True
    return not (has_password or user.mfa_enabled)
