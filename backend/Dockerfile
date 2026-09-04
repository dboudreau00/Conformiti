FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

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
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/api/health/ >/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
# Threaded workers, not the default sync ones: a malware scan occupies a
# worker for its duration, so three concurrent scans against a slow clamd
# would otherwise block 100% of the API, /api/health/ included.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--worker-class", "gthread", "--threads", "4", "--timeout", "90", "--access-logfile", "-"]
