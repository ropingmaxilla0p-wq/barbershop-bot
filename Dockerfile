# 💈 Barber Bot — Telegram Booking System
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (for SQLite and other potential libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files (excluding .env, __pycache__, .venv via .dockerignore)
COPY . .

# Expose WebApp port
EXPOSE 8080

# Default command: run the bot
CMD ["python", "main.py"]
