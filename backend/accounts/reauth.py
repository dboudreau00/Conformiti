"""Re-proving an account mid-session. Enrolling or removing a factor is how a hijacked session becomes permanent,
so each of those operations asks for proof here."""


def reauthenticated(request):
    """True if the caller just proved the account is theirs: the password, or a code from an enrolled factor (a backup
    code counts). An account with neither has nothing to prove with and nothing yet to protect: first enrolment."""
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
