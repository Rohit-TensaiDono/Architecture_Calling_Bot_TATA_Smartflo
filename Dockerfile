# Use official lightweight Python image
FROM python:3.12-slim

# Environment settings
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app

# Run the application
#CMD ["python", "main.py"]
CMD ["python", "smartflo_server.py"]
