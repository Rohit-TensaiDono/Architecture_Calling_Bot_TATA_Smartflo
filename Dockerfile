# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    gcc \
    python3-dev \
    libffi-dev \
    libssl-dev \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip tools
RUN pip install --upgrade pip setuptools wheel

# Install torch separately (IMPORTANT for whisper)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Copy requirements
COPY requirements.txt .

# Install remaining dependencies
RUN pip install --no-cache-dir -r requirements.txt
