"""
Backend FastAPI pour Solution 1 (Redis + PostgreSQL)
Cache Redis + Persistance PostgreSQL + Streaming LLM
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, Text, DateTime, Float, select, text  
import os
import json
import uuid
import hashlib
from datetime import datetime
from typing import AsyncIterator, Optional, List
import asyncio

# ==================== CONFIGURATION ====================

app = FastAPI(
    title="Chatbot LLM Backend - Redis + PostgreSQL",
    description="Backend avec cache Redis et persistance PostgreSQL",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Variables d'environnement
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

# Redis
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_TTL = int(os.getenv("REDIS_TTL", 3600))  # 1 heure

# PostgreSQL
POSTGRES_USER = os.getenv("POSTGRES_USER", "chatbot")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "changeme")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = os.getenv("POSTGRES_DB", "chatbot_db")

DATABASE_URL = f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# Clients LLM
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# Redis Client (initialisé au startup)
redis_client = None

# PostgreSQL Engine
postgres_engine = None
AsyncSessionLocal = None

# ==================== DATABASE MODELS ====================

Base = declarative_base()

class ChatTask(Base):
    """Modèle pour les tâches de chat"""
    __tablename__ = "chat_tasks"
    
    id = Column(String, primary_key=True)
    prompt = Column(Text, nullable=False)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    temperature = Column(Float, default=0.7)
    status = Column(String, default="created")
    full_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    cached = Column(Integer, default=0)  # 0 = non cached, 1 = cached

class ChatChunk(Base):
    """Modèle pour les chunks de chat"""
    __tablename__ = "chat_chunks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    chunk_id = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# ==================== MODELS ====================

class ChatRequest(BaseModel):
    prompt: str
    provider: str = "openai"
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4000

class TaskResponse(BaseModel):
    task_id: str
    status: str
    provider: str
    model: str
    cached: bool = False

# ==================== REDIS CACHE ====================

def generate_cache_key(prompt: str, provider: str, model: str) -> str:
    """Générer clé de cache"""
    key_string = f"{prompt}:{provider}:{model}"
    hash_key = hashlib.sha256(key_string.encode()).hexdigest()
    return f"chat:cache:{hash_key}"

async def get_from_cache(cache_key: str) -> Optional[dict]:
    """Récupérer depuis cache Redis"""
    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            return json.loads(cached_data)
    except Exception as e:
        print(f"Cache get error: {e}")
    return None

async def save_to_cache(cache_key: str, data: dict, ttl: int = REDIS_TTL):
    """Sauvegarder dans cache Redis"""
    try:
        await redis_client.setex(
            cache_key,
            ttl,
            json.dumps(data)
        )
    except Exception as e:
        print(f"Cache save error: {e}")

# ==================== POSTGRESQL PERSISTENCE ====================

async def save_task_to_db(
    task_id: str,
    prompt: str,
    provider: str,
    model: str,
    temperature: float,
    status: str = "created",
    cached: int = 0
):
    """Sauvegarder tâche dans PostgreSQL"""
    async with AsyncSessionLocal() as session:
        task = ChatTask(
            id=task_id,
            prompt=prompt,
            provider=provider,
            model=model,
            temperature=temperature,
            status=status,
            cached=cached
        )
        session.add(task)
        await session.commit()

async def update_task_status(task_id: str, status: str, error: str = None):
    """Mettre à jour status de tâche"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM chat_tasks WHERE id = :task_id"),
            {"task_id": task_id}
        )
        
        task = result.first()
        
        if task:
            error_part = f", error = '{error}'" if error else ""
            if error:
                await session.execute(
                    text("""
                        UPDATE chat_tasks 
                        SET status = :status, 
                            completed_at = :completed_at,
                            error = :error
                        WHERE id = :task_id
                    """),
                    {
                        "status": status,
                        "completed_at": datetime.utcnow().isoformat(),
                        "error": error,
                        "task_id": task_id
                    }
                )
            else:
                await session.execute(
                    text("""
                        UPDATE chat_tasks 
                        SET status = :status, 
                            completed_at = :completed_at
                        WHERE id = :task_id
                    """),
                    {
                        "status": status,
                        "completed_at": datetime.utcnow().isoformat(),
                        "task_id": task_id
                    }
                )
            

            await session.commit()

async def save_chunk_to_db(
    task_id: str,
    chunk_id: int,
    text: str,
    provider: str,
    model: str
):
    """Sauvegarder chunk dans PostgreSQL"""
    async with AsyncSessionLocal() as session:
        chunk = ChatChunk(
            task_id=task_id,
            chunk_id=chunk_id,
            text=text,
            provider=provider,
            model=model
        )
        session.add(chunk)
        await session.commit()

async def get_chunks_from_db(task_id: str, from_id: int = 0) -> List[dict]:
    """Récupérer chunks depuis PostgreSQL"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT * FROM chat_chunks 
                WHERE task_id = :task_id AND chunk_id >= :from_id 
                ORDER BY chunk_id
            """),
            {"task_id": task_id, "from_id": from_id}
        )
        
        rows = result.fetchall()
        
        return [
            {
                "chunk_id": row[2],
                "text": row[3],
                "provider": row[4],
                "model": row[5],
                "is_replay": False
            }
            for row in rows
        ]

async def save_full_response_to_db(task_id: str, full_response: str):
    """Sauvegarder réponse complète"""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                UPDATE chat_tasks 
                SET full_response = :full_response 
                WHERE id = :task_id
            """),
            {"full_response": full_response, "task_id": task_id}
        )
        
        await session.commit()
# ==================== LLM STREAMING ====================

async def stream_openai(
    prompt: str,
    task_id: str,
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 4000
) -> AsyncIterator[dict]:
    """Stream depuis OpenAI"""
    
    if not openai_client:
        raise HTTPException(status_code=500, detail="OpenAI not configured")
    
    stream = await openai_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True
    )
    
    chunk_id = 0
    full_response = ""
    
    async for chunk in stream:
        if chunk.choices[0].delta.content:
            text = chunk.choices[0].delta.content
            full_response += text
            
            # Sauvegarder chunk dans PostgreSQL
            await save_chunk_to_db(task_id, chunk_id, text, "openai", model)
            
            yield {
                "chunk_id": chunk_id,
                "text": text,
                "is_replay": False,
                "provider": "openai",
                "model": model
            }
            
            chunk_id += 1
    
    # Sauvegarder réponse complète
    await save_full_response_to_db(task_id, full_response)
    
   

async def stream_anthropic(
    prompt: str,
    task_id: str,
    model: str = "claude-3-5-sonnet-20241022",
    temperature: float = 0.7,
    max_tokens: int = 4000
) -> AsyncIterator[dict]:
    """Stream depuis Anthropic"""
    
    if not anthropic_client:
        raise HTTPException(status_code=500, detail="Anthropic not configured")
    
    chunk_id = 0
    full_response = ""
    
    async with anthropic_client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}]
    ) as stream:
        async for text in stream.text_stream:
            full_response += text
            
            # Sauvegarder chunk dans PostgreSQL
            await save_chunk_to_db(task_id, chunk_id, text, "anthropic", model)
            
            yield {
                "chunk_id": chunk_id,
                "text": text,
                "is_replay": False,
                "provider": "anthropic",
                "model": model
            }
            
            chunk_id += 1
    
    # Sauvegarder réponse complète
    await save_full_response_to_db(task_id, full_response)
    


# ==================== ENDPOINTS ====================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Chatbot LLM Backend - Redis + PostgreSQL",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health():
    """Health check"""
    
    # Test Redis
    redis_ok = False
    try:
        await redis_client.ping()
        redis_ok = True
    except:
        pass
    
    # Test PostgreSQL
    postgres_ok = False
    try:
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        postgres_ok = True
    except Exception as e:
        print(f"PostgreSQL health check error: {e}")
    
    return {
        "status": "healthy" if (redis_ok and postgres_ok) else "degraded",
        "openai_configured": openai_client is not None,
        "anthropic_configured": anthropic_client is not None,
        "redis_connected": redis_ok,
        "postgres_connected": postgres_ok
    }
@app.post("/api/chat/generate", response_model=TaskResponse)
async def create_chat_task(request: ChatRequest):
    """
    Créer une tâche de génération avec cache Redis
    
    Flow:
    1. Générer cache key
    2. Check cache Redis
    3. Si hit → retourner depuis cache
    4. Si miss → générer et sauvegarder
    """
    
    # Déterminer modèle
    model = request.model
    if not model:
        model = OPENAI_MODEL if request.provider == "openai" else ANTHROPIC_MODEL
    
    # Générer cache key
    cache_key = generate_cache_key(request.prompt, request.provider, model)
    
    # Check cache
    cached_data = await get_from_cache(cache_key)
    
    if cached_data:
        # CACHE HIT !
        task_id = str(uuid.uuid4())
        
        # Sauvegarder dans DB comme cached
        await save_task_to_db(
            task_id,
            request.prompt,
            request.provider,
            model,
            request.temperature,
            status="completed",
            cached=1
        )
        
        # Reconstruire chunks depuis cached response
        full_response = cached_data["full_response"]
        chunk_size = 50
        chunks = [full_response[i:i+chunk_size] for i in range(0, len(full_response), chunk_size)]
        
        for i, chunk_text in enumerate(chunks):
            await save_chunk_to_db(task_id, i, chunk_text, request.provider, model)
        
        await save_full_response_to_db(task_id, full_response)
        await update_task_status(task_id, "completed")
        
        return TaskResponse(
            task_id=task_id,
            status="completed",
            provider=request.provider,
            model=model,
            cached=True
        )
    
    # CACHE MISS - générer
    task_id = str(uuid.uuid4())
    
    # Sauvegarder état initial
    await save_task_to_db(
        task_id,
        request.prompt,
        request.provider,
        model,
        request.temperature
    )
    
    # Démarrer génération en arrière-plan
    asyncio.create_task(
        generate_with_cache_save(
            task_id,
            request.prompt,
            request.provider,
            model,
            request.temperature,
            request.max_tokens,
            cache_key
        )
    )
    
    return TaskResponse(
        task_id=task_id,
        status="running",
        provider=request.provider,
        model=model,
        cached=False
    )

async def generate_with_cache_save(
    task_id: str,
    prompt: str,
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int,
    cache_key: str
):
    """Génération en arrière-plan avec sauvegarde cache"""
    
    try:
        # Update status
        await update_task_status(task_id, "running")
        
        # Stream
        full_response = ""
        if provider == "openai":
            async for chunk in stream_openai(prompt, task_id, model, temperature, max_tokens):
                full_response += chunk["text"]
        else:
            async for chunk in stream_anthropic(prompt, task_id, model, temperature, max_tokens):
                full_response += chunk["text"]
        
        # Sauvegarder dans cache Redis
        await save_to_cache(cache_key, {
            "full_response": full_response,
            "provider": provider,
            "model": model
        })
        
        # Completed
        await update_task_status(task_id, "completed")
    
    except Exception as e:
        await update_task_status(task_id, "error", str(e))

@app.get("/api/chat/status/{task_id}")
async def get_task_status(task_id: str):
    """Obtenir status d'une tâche"""
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM chat_tasks WHERE id = :task_id"),
            {"task_id": task_id}
        )
        
        row = result.first()
        
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return {
            "task_id": row[0],
            "status": row[4],
            "provider": row[2],
            "model": row[3],
            "cached": bool(row[8]),
            "created_at": row[6].isoformat() if row[6] else None,
            "completed_at": row[7].isoformat() if row[7] else None
        }

@app.get("/api/chat/chunks/{task_id}")
async def get_chunks(task_id: str, from_id: int = 0):
    """Récupérer chunks d'une tâche"""
    
    chunks = await get_chunks_from_db(task_id, from_id)
    
    return {
        "task_id": task_id,
        "chunks": chunks,
        "total": len(chunks)
    }

@app.get("/api/stats")
async def get_stats():
    """Statistiques cache et DB"""
    
    async with AsyncSessionLocal() as session:
        # Total tasks
        result = await session.execute(text("SELECT COUNT(*) FROM chat_tasks"))
        total_tasks = result.scalar()
        
        # Cached tasks
       
        result = await session.execute(
            text("SELECT COUNT(*) FROM chat_tasks WHERE cached = 1")
        )
        cached_tasks = result.scalar()
        
        # Total chunks
        result = await session.execute(text("SELECT COUNT(*) FROM chat_chunks"))
        total_chunks = result.scalar()
        
        return {
            "total_tasks": total_tasks,
            "cached_tasks": cached_tasks,
            "cache_hit_rate": f"{(cached_tasks/total_tasks*100):.1f}%" if total_tasks > 0 else "0%",
            "total_chunks": total_chunks
        }

# ==================== STARTUP/SHUTDOWN ====================

@app.on_event("startup")
async def startup():
    """Initialisation au démarrage"""
    global redis_client, postgres_engine, AsyncSessionLocal
    
    print("🚀 Starting Redis + PostgreSQL Backend...")
    
    # Connexion Redis
    try:
        redis_client = await redis.from_url(
            f"redis://{REDIS_HOST}:{REDIS_PORT}",
            encoding="utf-8",
            decode_responses=True
        )
        await redis_client.ping()
        print(f"✅ Redis connected: {REDIS_HOST}:{REDIS_PORT}")
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
    
    # Connexion PostgreSQL
    try:
        postgres_engine = create_async_engine(DATABASE_URL, echo=False)
        AsyncSessionLocal = sessionmaker(
            postgres_engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Créer tables
        async with postgres_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        print(f"✅ PostgreSQL connected: {POSTGRES_HOST}:{POSTGRES_PORT}")
    except Exception as e:
        print(f"❌ PostgreSQL connection failed: {e}")
    
    print(f"   OpenAI configured: {openai_client is not None}")
    print(f"   Anthropic configured: {anthropic_client is not None}")
    print(f"   Cache TTL: {REDIS_TTL}s")

@app.on_event("shutdown")
async def shutdown():
    """Nettoyage à l'arrêt"""
    if redis_client:
        await redis_client.close()
    if postgres_engine:
        await postgres_engine.dispose()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
