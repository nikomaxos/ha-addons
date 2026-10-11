FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    nodejs \
    npm \
    jq \
    default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure any CLI executables are runnable
RUN chmod +x codex* agy* 2>/dev/null || true

EXPOSE 8000

CMD ["python", "server.py"]
