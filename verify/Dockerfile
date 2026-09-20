FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        "fastapi==0.141.1" "uvicorn[standard]==0.53.0" "pydantic==2.13.5" \
        httpx pytest

WORKDIR /app
COPY verify_checks.py verify.sh ./
RUN chmod +x /app/verify.sh

ENTRYPOINT ["/app/verify.sh"]
