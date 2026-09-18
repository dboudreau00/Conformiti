FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# The code default is DEBUG on, because the code's usual caller is a developer
# running `manage.py runserver`. This image's caller is `docker run`, which is
# a server. Compose and both installers set this explicitly, so a published
# image was the one path that reached the code default and came up with the
# browsable API, session authentication on every route, and MEDIA_ROOT served
# around the X-Accel check. Override it on purpose through compose with
# CONFORMITI_DEBUG; nothing else should.
ENV DJANGO_DEBUG=false

# And the other half of the same decision. BEHIND_TLS defaults to "not DEBUG",
# so pinning DEBUG off turned SECURE_SSL_REDIRECT on, and a plain `docker run`
# answered every request with a 301 to https that nothing was listening on.
# The compose file this image was built for sets BEHIND_TLS=false, because it
# serves plain HTTP on the LAN until an operator puts TLS in front; the image
# defaults the same way, for the same reason. Set BEHIND_TLS=true once TLS is
# terminated ahead of it, which is what INSTALL.md's production section says.
ENV BEHIND_TLS=false

WORKDIR /app

# psycopg ships binary wheels, so no compiler or libpq headers are needed.
# curl is kept for the container healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
COPY entrypoint.sh /entrypoint.sh

# Run as an unprivileged user. The writable locations are created here (and
# owned by that user) so fresh named volumes inherit the right ownership.
RUN useradd --system --create-home --uid 10001 app \
    && sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh \
    && mkdir -p /app/media /app/staticfiles /app/secrets /data/compliance-data \
    && chown -R app:app /app /data
USER app

EXPOSE 8000
# The status code is checked, not merely curl's exit code: `curl -f` treats a
# redirect as success, so a container answering every request with a 301 to a
# port nothing listens on reported itself healthy (0.9.5f).
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
    CMD test "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health/)" = 200 || exit 1

ENTRYPOINT ["/entrypoint.sh"]
# Threaded workers, not the default sync ones: a malware scan occupies a
# worker for its duration, so three concurrent scans against a slow clamd
# would otherwise block 100% of the API, /api/health/ included.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--worker-class", "gthread", "--threads", "4", "--timeout", "90", "--access-logfile", "-"]
