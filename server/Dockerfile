# Calculation server: FastAPI + pandas/NumPy/TA-Lib. Build on the Mac with
#   docker buildx build --platform linux/amd64 ...
# The Synology's Celeron J4125 has no AVX/AVX2; stick to wheels that do runtime CPU dispatch.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CONFIG_DIR=/config

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY migrations ./migrations
COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd --system --uid 10001 graadmeter && chmod +x /usr/local/bin/docker-entrypoint.sh
USER graadmeter

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status == 200 else 1)"
ENTRYPOINT ["docker-entrypoint.sh"]
# One worker only: the in-process scheduler must not run twice.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

# Test image: `scripts/test.sh` builds this target; the default build stays the runtime image.
FROM runtime AS test
USER root
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY tests ./tests
USER graadmeter
ENTRYPOINT []
CMD ["python", "-m", "pytest"]

FROM runtime
