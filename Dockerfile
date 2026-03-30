# Base image (MANDATORY)
FROM python:3.12-slim

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

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

# Install torch separately (for whisper)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose port
EXPOSE 8000

# Run app (update if needed)
CMD ["uvicorn", "smartflo_server:app", "--host", "0.0.0.0", "--port", "8000"]
