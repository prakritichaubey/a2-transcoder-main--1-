# ---- base image ----
FROM python:3.12-slim

# System deps (ffmpeg + certs); keep image small
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Workdir
WORKDIR /app

# ---- python deps (cached) ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- app code ----
# Copy your package; no need to re-copy static separately
COPY app ./app

# Ensure runtime dirs exist
RUN mkdir -p /app/app/data/incoming /app/app/data/outputs

# Run as non-root
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Runtime env
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Expose the API port (match your docker run -p 8000:8000)
EXPOSE 8000

# Start the API
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
