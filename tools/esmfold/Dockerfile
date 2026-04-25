# ESMFold requires PyTorch + CUDA. Use the official PyTorch base image.
# Adjust CUDA version to match your GPU instance (sm_80 = A100, sm_86 = A10G/3090).
FROM pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime

WORKDIR /app

# fair-esm pulls in ~2 GB of model weights on first run; pre-download in build
# by setting the cache dir to a layer we can cache in CI.
ENV TORCH_HOME=/app/.cache/torch
ENV ESM_DATA=/app/.cache/esm

RUN pip install --no-cache-dir \
    "fair-esm[esmfold]" \
    fastapi \
    "uvicorn[standard]" \
    && python -c "import esm; esm.pretrained.esmfold_v1()" \
    || echo "Pre-download skipped (no GPU at build time)"

COPY server.py .

EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
