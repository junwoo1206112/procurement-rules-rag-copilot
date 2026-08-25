FROM python:3.12-slim
WORKDIR /service
COPY pyproject.toml ./
# The Compose profile is the documented CPU demo path.  Install the CPU wheel
# first so sentence-transformers does not resolve CUDA runtime packages.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch
RUN pip install --no-cache-dir .
COPY app ./app
# Runtime uses only locally verified, versioned corpus snapshots; embedding
# caches and API secrets are intentionally excluded from the image.
COPY data/procurement-rules-manifest.json data/collected-chunks.json data/g2b-service-manifest.json data/g2b-service-chunks.json data/g2b-rfp-manifest.json data/g2b-rfp-chunks.json ./data/
COPY docs ./docs
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
