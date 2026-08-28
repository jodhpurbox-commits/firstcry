FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . /app

# Expose Render standard web port
EXPOSE 10000

ENV PORT=10000
ENV PYTHONUNBUFFERED=1

CMD ["python", "meeshoshop_bot.py"]
