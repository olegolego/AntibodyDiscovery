# RFdiffusion ships its own conda env; easiest to build from their repo.
# Clone and install per https://github.com/RosettaCommons/RFdiffusion
FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime

WORKDIR /app

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install RFdiffusion dependencies (SE3Transformer, etc.)
RUN pip install --no-cache-dir \
    dgl -f https://data.dgl.ai/wheels/cu117/repo.html \
    e3nn \
    wandb \
    pydantic \
    fastapi \
    "uvicorn[standard]"

# Clone RFdiffusion (pin to a known-good commit in production)
RUN git clone https://github.com/RosettaCommons/RFdiffusion.git /rfdiffusion \
    && pip install --no-cache-dir /rfdiffusion

# Download model weights (large — consider mounting a volume instead)
# RUN python /rfdiffusion/scripts/download_models.py /rfdiffusion/models

COPY server.py .

EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
