FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PUBLIC_BIND=1 \
    MODEL_PROVIDER=off \
    WORKSPACE_DB=/data/workspaces.sqlite3 \
    PORT=8000
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 studio \
    && useradd --uid 10001 --gid studio --no-create-home --no-log-init studio \
    && install -d -o studio -g studio -m 0750 /data
COPY app.py studio.py providers.py pipeline.py example.json ./
COPY web/ web/
USER 10001:10001
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['PORT'] + '/health', timeout=3).close()"
CMD ["sh", "-c", "exec gunicorn --bind \"0.0.0.0:${PORT:-8000}\" --workers 1 --threads 4 --timeout 240 --access-logfile - app:application"]
