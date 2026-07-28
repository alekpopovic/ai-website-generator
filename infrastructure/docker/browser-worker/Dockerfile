FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /workspace

COPY packages/python/platform-clients packages/python/platform-clients
COPY packages/python/platform-workflows packages/python/platform-workflows
COPY apps/api apps/api
COPY services/browser-worker services/browser-worker

RUN python -m pip install --no-cache-dir \
      ./packages/python/platform-clients \
      ./packages/python/platform-workflows \
      ./apps/api \
      ./services/browser-worker \
    && python -m pip check

USER pwuser

ENTRYPOINT ["platform-browser-worker"]
