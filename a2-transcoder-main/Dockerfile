# base
FROM python:3.11-slim

# install ffmpeg (CPU encoder)
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# create workdir
WORKDIR /app

# Copy and install deps first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY app ./app
COPY app/static ./app/static

# Ensure data folders exist
RUN mkdir -p /app/app/data/incoming /app/app/data/outputs

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
