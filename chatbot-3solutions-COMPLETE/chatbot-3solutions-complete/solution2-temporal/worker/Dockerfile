FROM --platform=linux/arm64 python:3.11-slim

WORKDIR /app

# Installer uv
RUN pip install uv

# Copier requirements
COPY requirements.txt .

# Installer avec uv
RUN uv pip install --system -r requirements.txt

# Copier code
COPY worker.py workflows.py activities.py ./

# Créer storage
RUN mkdir -p /app/storage

CMD ["python", "worker.py"]
