# Cloud Run image for the public deployment.
# Build & deploy: gcloud run deploy kor-teacher --source . --region asia-northeast3 ...
# The data/ folder (SQLite library, E5 ONNX model, page text) is copied into the
# image; the source PDFs and .runtime are excluded by .gcloudignore/.dockerignore.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PUBLIC=1 \
    HOST=0.0.0.0 \
    PORT=8080

# One thread each for the BGE-M3 query model and numpy: the service gets 1 vCPU
# (deploy.json), and os.cpu_count() inside Cloud Run reports the host's cores.
ENV BGE_M3_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8080
CMD ["python", "server.py"]
