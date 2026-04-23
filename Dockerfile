FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libegl1 \
    libfontconfig1 \
    libdbus-1-3 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY sample_data/ /app/sample_data/

ENV QT_QPA_PLATFORM=offscreen

EXPOSE 8001
CMD ["python", "server.py"]