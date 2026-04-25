FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ABMAP_HOME=/opt/abmap \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/xdg-cache

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    hmmer \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    numpy \
    scipy \
    pandas \
    torch \
    biopython \
    matplotlib \
    seaborn \
    tqdm \
    scikit-learn \
    h5py \
    positional_encodings \
    dscript

RUN git clone https://github.com/rs239/abmap.git "${ABMAP_HOME}" \
    && git -C "${ABMAP_HOME}" checkout 3d8ef30180d0bc2e2657ae38ae37c77228a0703b

RUN pip install --no-cache-dir -e "${ABMAP_HOME}"

RUN python - <<'PY'
import os
import shutil
import subprocess
import urllib.request

from dscript.pretrained import get_state_dict_path

url = "http://cb.csail.mit.edu/cb/dscript/data/models/dscript_lm_v1.pt"
destination = get_state_dict_path("lm_v1")
os.makedirs(os.path.dirname(destination), exist_ok=True)

try:
    with urllib.request.urlopen(url) as response, open(destination, "wb") as output:
        shutil.copyfileobj(response, output)
except Exception:
    subprocess.check_call(["curl", "-Lk", url, "-o", destination])
PY

COPY server.py /app/server.py

EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
