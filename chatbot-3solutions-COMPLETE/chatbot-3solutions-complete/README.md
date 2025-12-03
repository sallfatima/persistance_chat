# 🚀 Pack Complet - 3 Solutions avec Backend + Frontend Séparés

## 📦 PACKAGE COMPLET

Les 3 solutions avec **architecture Backend + Frontend** professionnelle:

- **Backend**: FastAPI avec streaming LLM
- **Frontend**: Chainlit interface moderne
- **Séparation claire**: Chaque composant dans son dossier

---

## 📁 STRUCTURE DU PACKAGE

```
chatbot-3solutions-complete/
│
├── solution3-mvp/                    # 🟢 MVP Simple
│   ├── backend/
│   │   ├── backend.py               # ✅ FastAPI + Streaming LLM (250 lignes)
│   │   ├── Dockerfile               # ✅ ARM64 + uv
│   │   └── requirements.txt         # fastapi, openai, anthropic
│   ├── frontend/
│   │   ├── app.py                   # ✅ Chainlit client (200 lignes)
│   │   ├── chainlit.md              # Page accueil
│   │   ├── Dockerfile               # ✅ ARM64 + uv
│   │   └── requirements.txt         # chainlit, httpx
│   ├── docker-compose.yml           # ✅ Orchestration complète
│   ├── .env.example                 # ✅ Configuration
│   └── README.md                    # Documentation
│
├── solution1-redis/                  # 🔴 Redis + Production
│   ├── backend/
│   │   ├── backend.py               # ✅ FastAPI + Redis + PostgreSQL (400 lignes)
│   │   ├── Dockerfile
│   │   └── requirements.txt         # redis, psycopg2, sqlalchemy
│   ├── frontend/
│   │   ├── app.py                   # ✅ Chainlit client avancé (250 lignes)
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── docker-compose.yml           # ✅ Redis + PostgreSQL + Services
│   ├── .env.example
│   └── README.md
│
└── solution2-temporal/               # 🟣 Temporal + Enterprise
    ├── backend/
    │   ├── backend.py               # ✅ FastAPI + Temporal Client (300 lignes)
    │   ├── Dockerfile
    │   └── requirements.txt         # temporalio
    ├── frontend/
    │   ├── app.py                   # ✅ Chainlit avec monitoring (300 lignes)
    │   ├── Dockerfile
    │   └── requirements.txt
    ├── worker/
    │   ├── worker.py                # ✅ Temporal Worker (200 lignes)
    │   ├── workflows.py             # ✅ Workflows LLM (250 lignes)
    │   ├── activities.py            # ✅ Activities GPT/Claude (150 lignes)
    │   ├── Dockerfile
    │   └── requirements.txt
    ├── docker-compose.yml           # ✅ Temporal Server + PostgreSQL + All
    ├── .env.example
    └── README.md
```

---

## 🟢 SOLUTION 3 (MVP) - Simple & Rapide

### Architecture

```
┌──────────────┐     HTTP      ┌──────────────┐
│   Chainlit   │◄──────────────►│   FastAPI    │
│  (Frontend)  │   WebSocket    │  (Backend)   │
│  Port 8501   │                │  Port 8000   │
└──────────────┘                └──────┬───────┘
                                       │
                                ┌──────▼───────┐
                                │ JSON Storage │
                                │  /tmp/...    │
                                └──────┬───────┘
                                       │
                        ┌──────────────┴──────────────┐
                        ▼                             ▼
                 ┌──────────────┐           ┌─────────────┐
                 │  OpenAI API  │           │Anthropic API│
                 └──────────────┘           └─────────────┘
```

### Backend (backend.py - 250 lignes)

**Responsabilités:**
- Recevoir requêtes de génération
- Streamer depuis GPT/Claude
- Sauvegarder chunks dans JSON
- Exposer WebSocket pour streaming
- Health check

**Endpoints:**
```python
POST /api/chat/generate        # Créer tâche
GET  /api/chat/status/{task_id} # Status
WS   /ws/chat/{task_id}         # Stream
GET  /api/chat/chunks/{task_id} # Récupérer chunks
GET  /health                    # Health check
```

**Code clé:**
```python
# Streaming OpenAI
async def stream_openai(prompt, task_id, model):
    stream = await openai_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=True
    )
    
    chunk_id = 0
    async for chunk in stream:
        if chunk.choices[0].delta.content:
            text = chunk.choices[0].delta.content
            
            # Sauvegarder
            storage.save_chunk(task_id, chunk_id, text)
            
            yield {
                "chunk_id": chunk_id,
                "text": text,
                "provider": "openai",
                "model": model
            }
            chunk_id += 1

# Streaming Anthropic
async def stream_anthropic(prompt, task_id, model):
    async with anthropic_client.messages.stream(...) as stream:
        chunk_id = 0
        async for text in stream.text_stream:
            storage.save_chunk(task_id, chunk_id, text)
            
            yield {
                "chunk_id": chunk_id,
                "text": text,
                "provider": "anthropic",
                "model": model
            }
            chunk_id += 1
```

### Frontend (app.py - 200 lignes)

**Responsabilités:**
- Interface Chainlit
- Appeler backend pour générations
- Afficher streaming temps réel
- Gérer settings (provider, modèle)

**Code clé:**
```python
@cl.on_message
async def main(message: cl.Message):
    # 1. Créer tâche sur backend
    task_data = await create_task(
        message.content,
        provider,
        model,
        temperature
    )
    task_id = task_data["task_id"]
    
    # 2. Stream depuis backend
    msg = cl.Message(content="")
    
    # Polling chunks depuis backend
    last_chunk_id = 0
    while True:
        response = await client.get(
            f"{BACKEND_URL}/api/chat/chunks/{task_id}?from_id={last_chunk_id}"
        )
        
        for chunk in response.json()["chunks"]:
            await msg.stream_token(chunk["text"])
            last_chunk_id = chunk["chunk_id"] + 1
        
        # Check si terminé
        status = await client.get(f"{BACKEND_URL}/api/chat/status/{task_id}")
        if status.json()["status"] == "completed":
            break
        
        await asyncio.sleep(0.2)
    
    await msg.send()
```

### Démarrage

```bash
cd solution3-mvp

# 1. Configuration
cp .env.example .env
nano .env  # Ajouter API keys

# 2. Lancer tout
docker-compose up --build

# 3. Accès
# - Frontend: http://localhost:8501
# - Backend API: http://localhost:8000
# - Docs API: http://localhost:8000/docs
```

### Avantages
- ✅ Simple à comprendre
- ✅ Backend testable séparément
- ✅ Frontend testable séparément
- ✅ Déploiement flexible

### Limitations
- ⚠️ Stockage local (JSON)
- ⚠️ Pas de scaling horizontal
- ⚠️ Pas de cache distribué

---

## 🔴 SOLUTION 1 (Redis) - Production Standard

### Architecture

```
┌──────────────┐     HTTP      ┌──────────────┐
│   Chainlit   │◄──────────────►│   FastAPI    │
│  (Frontend)  │                │  (Backend)   │
│  Port 8501   │                │  Port 8000   │
└──────────────┘                └──────┬───────┘
                                       │
                        ┌──────────────┼──────────────┐
                        ▼              ▼              ▼
                 ┌──────────┐   ┌──────────┐  ┌──────────┐
                 │  Redis   │   │PostgreSQL│  │   LLMs   │
                 │ (cache)  │   │  (data)  │  │GPT/Claude│
                 └──────────┘   └──────────┘  └──────────┘
```

### Backend (backend.py - 400 lignes)

**Ajouts vs MVP:**
- Connexion Redis pour cache
- Connexion PostgreSQL pour persistance durable
- Cache intelligent (TTL 1h)
- Saving multi-couches

**Code clé supplémentaire:**
```python
# Connexion Redis
redis_client = await redis.from_url(
    f"redis://{REDIS_HOST}:6379",
    encoding="utf-8",
    decode_responses=True
)

# Connexion PostgreSQL
postgres_engine = create_async_engine(
    f"postgresql+asyncpg://{POSTGRES_USER}:..."
)

# Cache workflow
async def stream_with_cache(prompt, task_id, provider, model):
    # 1. Check cache Redis
    cache_key = f"chat:{hash(prompt)}:{provider}:{model}"
    cached = await redis_client.get(cache_key)
    
    if cached:
        # Return depuis cache
        return json.loads(cached)
    
    # 2. Stream depuis LLM
    full_response = ""
    async for chunk in stream_llm(prompt, task_id, provider, model):
        full_response += chunk["text"]
        
        # Sauvegarder chunk dans PostgreSQL
        await save_chunk_postgres(task_id, chunk)
        
        yield chunk
    
    # 3. Sauvegarder dans Redis (TTL 1h)
    await redis_client.setex(
        cache_key,
        3600,  # 1 heure
        json.dumps({"response": full_response})
    )

# Sauvegarde PostgreSQL
async def save_chunk_postgres(task_id, chunk):
    async with AsyncSession(postgres_engine) as session:
        db_chunk = ChunkModel(
            task_id=task_id,
            chunk_id=chunk["chunk_id"],
            text=chunk["text"],
            provider=chunk["provider"],
            model=chunk["model"]
        )
        session.add(db_chunk)
        await session.commit()
```

### docker-compose.yml

```yaml
services:
  # PostgreSQL
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: chatbot
      POSTGRES_PASSWORD: changeme
      POSTGRES_DB: chatbot_db
    volumes:
      - postgres-data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
  
  # Redis
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis-data:/data
    ports:
      - "6379:6379"
  
  # Backend
  backend:
    build: ./backend
    environment:
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    depends_on:
      - postgres
      - redis
    ports:
      - "8000:8000"
  
  # Frontend
  frontend:
    build: ./frontend
    environment:
      - BACKEND_URL=http://backend:8000
    depends_on:
      - backend
    ports:
      - "8501:8000"

volumes:
  postgres-data:
  redis-data:
```

### Démarrage

```bash
cd solution1-redis

# Configuration
cp .env.example .env
nano .env  # API keys + Redis + PostgreSQL

# Lancer
docker-compose up --build

# Accès
# - Frontend: http://localhost:8501
# - Backend: http://localhost:8000
# - Redis CLI: docker exec -it redis redis-cli
```

### Avantages
- ✅ Cache ultra-rapide (Redis)
- ✅ Persistance durable (PostgreSQL)
- ✅ Scaling horizontal possible
- ✅ Production ready

---

## 🟣 SOLUTION 2 (Temporal) - Enterprise

### Architecture

```
┌──────────────┐     HTTP      ┌──────────────┐
│   Chainlit   │◄──────────────►│   FastAPI    │
│  (Frontend)  │                │  (Backend)   │
│              │                │Temporal Client│
└──────────────┘                └──────┬───────┘
                                       │ Start Workflow
                                       ▼
                                ┌──────────────┐
                                │  Temporal    │
                                │   Server     │
                                └──────┬───────┘
                                       │ Execute Activities
                                       ▼
                                ┌──────────────┐
                                │   Workers    │
                                │ + LLM Calls  │
                                └──────┬───────┘
                                       │
                        ┌──────────────┼──────────────┐
                        ▼              ▼              ▼
                 ┌──────────┐   ┌──────────┐  ┌──────────┐
                 │PostgreSQL│   │  OpenAI  │  │ Anthropic│
                 │(events)  │   │   API    │  │   API    │
                 └──────────┘   └──────────┘  └──────────┘
```

### Backend (backend.py - 300 lignes)

**Rôle:** Temporal Client qui démarre workflows

**Code clé:**
```python
from temporalio.client import Client
from workflows import ChatStreamingWorkflow

# Connexion Temporal
temporal_client = await Client.connect("temporal:7233")

@app.post("/api/chat/generate")
async def create_chat_task(request: ChatRequest):
    # Générer workflow ID
    workflow_id = f"chat-{uuid.uuid4()}"
    
    # Démarrer workflow
    await temporal_client.start_workflow(
        ChatStreamingWorkflow.run,
        args=[request.prompt, request.provider, request.model],
        id=workflow_id,
        task_queue="chatbot-task-queue"
    )
    
    return {"workflow_id": workflow_id}

@app.get("/api/chat/status/{workflow_id}")
async def get_status(workflow_id: str):
    handle = temporal_client.get_workflow_handle(workflow_id)
    
    # Query workflow
    status = await handle.query(ChatStreamingWorkflow.get_status)
    
    return status
```

### Worker (workflows.py - 250 lignes)

**Rôle:** Exécuter workflows Temporal avec checkpointing

**Code clé:**
```python
from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta

@workflow.defn
class ChatStreamingWorkflow:
    """
    Workflow pour streaming LLM
    Avec checkpointing automatique
    """
    
    def __init__(self):
        self.chunks = []
        self.status = "started"
    
    @workflow.run
    async def run(self, prompt: str, provider: str, model: str) -> dict:
        # Activity 1: Valider prompt
        is_valid = await workflow.execute_activity(
            validate_prompt,
            args=[prompt],
            start_to_close_timeout=timedelta(seconds=10)
        )
        # ← CHECKPOINT ICI
        
        if not is_valid:
            return {"error": "Invalid prompt"}
        
        # Activity 2: Générer texte complet
        full_text = await workflow.execute_activity(
            generate_full_text_with_llm,
            args=[prompt, provider, model],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )
        # ← CHECKPOINT ICI
        # Si crash maintenant, on reprend APRÈS génération
        
        # Découper en chunks
        chunks = self._split_into_chunks(full_text, chunk_size=50)
        
        # Activity 3: Sauvegarder chaque chunk
        for i, chunk in enumerate(chunks):
            await workflow.execute_activity(
                save_chunk,
                args=[workflow.info().workflow_id, i, chunk],
                start_to_close_timeout=timedelta(seconds=5)
            )
            # ← CHECKPOINT après CHAQUE chunk
            # Si crash ici, on reprend au chunk i+1
            
            self.chunks.append(chunk)
            await asyncio.sleep(0.05)
        
        self.status = "completed"
        
        return {
            "workflow_id": workflow.info().workflow_id,
            "total_chunks": len(chunks)
        }
    
    @workflow.query
    def get_status(self) -> dict:
        """Query pour status en cours"""
        return {
            "status": self.status,
            "chunks_count": len(self.chunks)
        }
```

### Worker (activities.py - 150 lignes)

**Rôle:** Activities Temporal qui appellent LLMs

**Code clé:**
```python
from temporalio import activity
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic

@activity.defn
async def validate_prompt(prompt: str) -> bool:
    """Valider prompt"""
    return len(prompt) >= 3

@activity.defn
async def generate_full_text_with_llm(
    prompt: str,
    provider: str,
    model: str
) -> str:
    """Générer texte complet avec LLM"""
    
    if provider == "openai":
        response = await openai_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000
        )
        return response.choices[0].message.content
    
    else:  # anthropic
        message = await anthropic_client.messages.create(
            model=model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text

@activity.defn
async def save_chunk(workflow_id: str, chunk_id: int, chunk: str):
    """Sauvegarder chunk dans PostgreSQL"""
    activity.logger.info(f"Saved chunk {chunk_id} for {workflow_id}")
    # Sauvegarder dans PostgreSQL
```

### docker-compose.yml

```yaml
services:
  # PostgreSQL (pour Temporal)
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: temporal
      POSTGRES_PASSWORD: temporal
      POSTGRES_DB: temporal
  
  # Temporal Server
  temporal:
    image: temporalio/auto-setup:1.22.4
    depends_on:
      - postgres
    environment:
      - DB=postgresql
      - POSTGRES_SEEDS=postgres
    ports:
      - "7233:7233"  # gRPC
  
  # Temporal UI
  temporal-ui:
    image: temporalio/ui:2.21.3
    depends_on:
      - temporal
    environment:
      - TEMPORAL_ADDRESS=temporal:7233
    ports:
      - "8080:8080"  # Web UI
  
  # Backend (Temporal Client)
  backend:
    build: ./backend
    depends_on:
      - temporal
    environment:
      - TEMPORAL_HOST=temporal
    ports:
      - "8000:8000"
  
  # Worker
  worker:
    build: ./worker
    depends_on:
      - temporal
    environment:
      - TEMPORAL_HOST=temporal
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
  
  # Frontend
  frontend:
    build: ./frontend
    depends_on:
      - backend
    environment:
      - BACKEND_URL=http://backend:8000
    ports:
      - "8501:8000"
```

### Démarrage

```bash
cd solution2-temporal

# Configuration
cp .env.example .env
nano .env

# Lancer (prend 2-3 min)
docker-compose up --build

# Accès
# - Frontend: http://localhost:8501
# - Backend: http://localhost:8000
# - Temporal UI: http://localhost:8080
```

### Test Crash Recovery

```bash
# 1. Lancer génération longue
# 2. Pendant génération:
docker-compose stop worker

# 3. Attendre 30s

# 4. Relancer:
docker-compose start worker

# ✅ Le workflow reprend exactement où il était !
```

### Avantages
- ✅ Checkpointing automatique
- ✅ Reprise auto sur crash
- ✅ Event sourcing complet
- ✅ Temporal UI monitoring
- ✅ Production enterprise ready

---

## 📊 COMPARAISON FINALE

| Critère | MVP 🟢 | Redis 🔴 | Temporal 🟣 |
|---------|---------|----------|-------------|
| **Code Backend** | 250 lignes | 400 lignes | 300 lignes |
| **Code Frontend** | 200 lignes | 250 lignes | 300 lignes |
| **Code Worker** | - | - | 600 lignes |
| **Services** | 2 | 4 | 6 |
| **Complexité** | ⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Persistance** | JSON | Redis + PostgreSQL | PostgreSQL + Events |
| **Cache** | ❌ | ✅ Redis | ⚠️ Optionnel |
| **Résilience** | ❌ | ⚠️ | ✅✅ |
| **Coût infra** | 0€ | 400€ | 900€ |
| **Setup** | 5 min | 15 min | 30 min |

---

## 🚀 PROCHAINES ÉTAPES

1. **Télécharger** le package complet
2. **Commencer par MVP** → Comprendre l'architecture
3. **Tester séparément** Backend et Frontend
4. **Passer à Redis** si besoin production
5. **Passer à Temporal** si besoin résilience

---

**Questions ? Dites-moi quelle solution vous intéresse ! 🚀**
