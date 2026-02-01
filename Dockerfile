FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Set environment variables
ENV GITHUB_ACTIONS=true
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

# Run the script
# 默认启动 Web 服务，Web 服务会按需调用 checkin 脚本
ENV PORT=5000
EXPOSE 5000
CMD ["python", "app.py"]

# Optional web panel
EXPOSE 8080
