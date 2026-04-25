# Uses LocalColabFold which bundles AlphaFold2 + MMseqs2 MSA pipeline.
# See https://github.com/YoshitakaMo/localcolabfold for install instructions.
# This image assumes localcolabfold is installed at /colabfold.
FROM nvcr.io/nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

WORKDIR /app

RUN apt-get update && apt-get install -y \
    wget git python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install LocalColabFold (downloads ~5 GB of weights — layer-cache or mount a volume)
RUN wget -q https://raw.githubusercontent.com/YoshitakaMo/localcolabfold/main/install_colabfold_linux.sh \
    && bash install_colabfold_linux.sh /colabfold

ENV PATH="/colabfold/bin:$PATH"

RUN pip3 install --no-cache-dir fastapi "uvicorn[standard]"

COPY server.py .

EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
