# Use Python 3.10 base image
FROM python:3.10-slim

# Set workdir
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN python -m pip install --upgrade pip setuptools wheel

# Clone TTS repo
RUN git clone https://github.com/coqui-ai/TTS.git /app/TTS

# Install TTS in editable mode
RUN pip install -e /app/TTS

# Install pydub for MP3 handling
RUN pip install pydub

# Default command (bash shell)
CMD ["bash"]