FROM --platform=linux/arm64 python:3.11-slim

WORKDIR /app

# Installer uv
RUN pip install uv

# Copier requirements
COPY requirements.txt .

# Installer avec uv
RUN uv pip install --system -r requirements.txt

# Copier code
COPY app.py .
COPY chainlit.md .

EXPOSE 8000

CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
