# Target < 80 MB: alpine base, wheel-only installs (psutil ships musllinux wheels)
FROM python:3.12-alpine

RUN pip install --no-cache-dir --only-binary=:all: psutil httpx \
    && pip uninstall -y pip \
    && find /usr/local/lib/python3.12 -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; \
    rm -rf /root/.cache

WORKDIR /app
COPY vigil_agent ./vigil_agent

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "vigil_agent.main"]
