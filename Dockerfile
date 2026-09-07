FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --uid 10001 dockerdesk

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY docker-entrypoint.py .
COPY templates ./templates
COPY static ./static

RUN chown -R dockerdesk:dockerdesk /app

# Docker Compose supplies the host Docker socket GID as a supplementary group.
# Keep the actual Flask/Gunicorn process unprivileged.
USER dockerdesk

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"

ENTRYPOINT ["python", "/app/docker-entrypoint.py"]

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--access-logfile", "-", "--graceful-timeout", "5", "app:app"]
