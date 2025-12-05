FROM --platform=linux/arm64 python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Installer uv
RUN pip install uv

# Copier requirements
COPY requirements.txt .

# Installer avec uv
RUN uv pip install --system -r requirements.txt

# Copier code
COPY backend.py .

EXPOSE 8000

CMD ["uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "8000"]