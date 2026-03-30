# Use official Python image
FROM python:3.12-slim

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies (important for whisper, audio, builds)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    gcc \
    python3-dev \
    libffi-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip tools first (important for wheel builds)
RUN pip install --upgrade pip setuptools wheel

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose port (for FastAPI/Flask)
EXPOSE 8000

# Default command (CHANGE based on your app)
# If using FastAPI:
CMD ["uvicorn", "smartflo_server:app", "--host", "0.0.0.0", "--port", "8000"]

# If using Flask instead, comment above and use:
# CMD ["python", "smartflo_server.py"]
