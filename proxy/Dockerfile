FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY observability.py .

# Match the UID/GID used by file-based Docker secrets in this deployment.
# This keeps the proxy non-root while allowing reads from /run/secrets.
RUN groupadd -g 1001 appuser && useradd -u 1001 -g 1001 -m appuser
USER appuser

EXPOSE 3200

CMD ["python", "-u", "main.py"]
