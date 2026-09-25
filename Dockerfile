FROM node:22-bookworm-slim AS web
WORKDIR /web
# Only tsc + vite run here; the Playwright devDependency (used by local
# browser checks) must not pull its browser binaries into the image build.
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data FRONTEND_DIR=/app/web HOME=/tmp
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tini gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 soundleaf && useradd -u 1000 -g 1000 -M soundleaf \
    && mkdir /data && chown 1000:1000 /data
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY app/ ./app/
COPY --from=web /web/dist ./web
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
EXPOSE 8780
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8780/health/ready', timeout=4)"
# 容器默认以 root 启动：entrypoint 接管数据目录属主后降权到 1000:1000；
# compose 指定 user 时按该身份直接运行。
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8780", "--workers", "1", "--no-access-log"]
