FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY observability.py .

# Run as non-root user (uid 1000) - matches Docker secrets ownership
RUN useradd -u 1000 -m appuser
USER appuser

EXPOSE 3200

CMD ["python", "-u", "main.py"]
