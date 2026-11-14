FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-impress \
    poppler-utils \
    ffmpeg \
    espeak-ng \
    libsndfile1 \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU wheels of torch (for the pronunciation phone model) are much smaller than the default CUDA ones
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Bake the ~1.2 GB phone model into the image so a restart doesn't re-download it
RUN python -c "from openpronounce.phones import _load_model; _load_model()"

COPY . .

RUN mkdir -p uploads static/audio static/slides data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
