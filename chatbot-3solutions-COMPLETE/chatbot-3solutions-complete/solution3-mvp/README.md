# 🟢 Solution 3 (MVP) - Backend + Frontend Séparés

## Architecture

```
Chainlit (Frontend :8501) ↔ FastAPI (Backend :8000) ↔ GPT/Claude
```

## Structure

```
solution3-mvp/
├── backend/
│   ├── backend.py          # FastAPI avec streaming LLM (250 lignes)
│   ├── Dockerfile          # ARM64 + uv
│   └── requirements.txt    # fastapi, openai, anthropic
├── frontend/
│   ├── app.py              # Chainlit client (200 lignes)
│   ├── chainlit.md         # Page d'accueil
│   ├── Dockerfile          # ARM64 + uv
│   └── requirements.txt    # chainlit, httpx
├── docker-compose.yml      # Orchestration
└── .env.example            # Configuration
```

## Démarrage

```bash
# 1. Configuration
cp .env.example .env
nano .env  # Ajouter API keys

# 2. Lancer
docker-compose up --build

# 3. Accès
# - Frontend: http://localhost:8501
# - Backend: http://localhost:8000
# - API Docs: http://localhost:8000/docs
```

## Backend API

### Endpoints

- `POST /api/chat/generate` - Créer tâche
- `GET /api/chat/status/{task_id}` - Status
- `WS /ws/chat/{task_id}` - Stream WebSocket
- `GET /api/chat/chunks/{task_id}` - Récupérer chunks
- `GET /health` - Health check

### Test Backend Seul

```bash
# Lancer backend
cd backend
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
python backend.py

# Tester
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/chat/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Hello","provider":"openai"}'
```

## Frontend Chainlit

### Test Frontend Seul

```bash
# Lancer frontend (backend doit tourner)
cd frontend
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
export BACKEND_URL=http://localhost:8000
chainlit run app.py

# Accès: http://localhost:8000
```

## Avantages

- ✅ Backend testable indépendamment
- ✅ Frontend testable indépendamment
- ✅ Déploiement flexible
- ✅ Scaling séparé possible

Voir README principal pour plus de détails !
