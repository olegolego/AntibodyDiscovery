# ProteinMPNN works with PyTorch; no exotic CUDA ops, runs on most GPU images.
FROM pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime

WORKDIR /app

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/dauparas/ProteinMPNN.git /proteinmpnn

RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    biopython

ENV PYTHONPATH="/proteinmpnn:$PYTHONPATH"

# Model weights are checked into the repo (~130 MB); they come with the clone.

COPY server.py .

EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
