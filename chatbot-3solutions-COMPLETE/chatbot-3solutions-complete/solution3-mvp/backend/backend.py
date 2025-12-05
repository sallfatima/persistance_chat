"""
Backend FastAPI pour Solution 3 (MVP) avec Sessions
Support de reconnexion après F5
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
import os
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator, Optional, List
import asyncio

# ==================== CONFIGURATION ====================

app = FastAPI(
    title="Chatbot LLM Backend - MVP with Sessions",
    description="Backend avec gestion de sessions utilisateur",
    version="2.0.0"
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
STORAGE_PATH = Path(os.getenv("STORAGE_PATH", "/app/storage"))

# Créer dossier storage
STORAGE_PATH.mkdir(parents=True, exist_ok=True)

# Clients LLM
openai_client = None
anthropic_client = None

if OPENAI_API_KEY:
    try:
        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        print("✅ OpenAI client initialized")
    except Exception as e:
        print(f"⚠️ OpenAI initialization failed: {e}")

if ANTHROPIC_API_KEY:
    try:
        anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        print("✅ Anthropic client initialized")
    except Exception as e:
        print(f"⚠️ Anthropic initialization failed: {e}")

# ==================== MODELS ====================

class ChatRequest(BaseModel):
    prompt: str
    provider: str = "openai"
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4000
    user_id: Optional[str] = None

class TaskResponse(BaseModel):
    task_id: str
    status: str
    provider: str
    model: str
    user_id: str

class SessionInfo(BaseModel):
    task_id: str
    status: str
    prompt: str
    progress: float
    chunks_count: int
    created_at: str
    last_updated: str

# ==================== STORAGE WITH SESSIONS ====================

class SessionStorage:
    """Stockage avec gestion de sessions utilisateur"""
    
    @staticmethod
    def save_task_state(task_id: str, state: dict):
        """Sauvegarder état de tâche"""
        file_path = STORAGE_PATH / f"{task_id}_state.json"
        state["last_updated"] = datetime.now().isoformat()
        with open(file_path, 'w') as f:
            json.dump(state, f, indent=2)
    
    @staticmethod
    def get_task_state(task_id: str) -> Optional[dict]:
        """Récupérer état de tâche"""
        file_path = STORAGE_PATH / f"{task_id}_state.json"
        if file_path.exists():
            with open(file_path, 'r') as f:
                return json.load(f)
        return None
    
    @staticmethod
    def save_chunk(task_id: str, chunk_id: int, text: str, metadata: dict):
        """Sauvegarder un chunk"""
        file_path = STORAGE_PATH / f"{task_id}_chunks.json"
        
        chunks = []
        if file_path.exists():
            with open(file_path, 'r') as f:
                chunks = json.load(f)
        
        chunks.append({
            "chunk_id": chunk_id,
            "text": text,
            "timestamp": datetime.now().isoformat(),
            **metadata
        })
        
        with open(file_path, 'w') as f:
            json.dump(chunks, f, indent=2)
        
        # Mettre à jour progress
        state = SessionStorage.get_task_state(task_id)
        if state:
            state["last_chunk_id"] = chunk_id
            state["chunks_count"] = len(chunks)
            SessionStorage.save_task_state(task_id, state)
    
    @staticmethod
    def get_chunks(task_id: str, from_id: int = 0) -> List[dict]:
        """Récupérer chunks depuis un ID"""
        file_path = STORAGE_PATH / f"{task_id}_chunks.json"
        if file_path.exists():
            with open(file_path, 'r') as f:
                chunks = json.load(f)
            return [c for c in chunks if c['chunk_id'] >= from_id]
        return []
    
    @staticmethod
    def get_user_active_tasks(user_id: str) -> List[SessionInfo]:
        """Récupérer toutes les tâches actives d'un utilisateur"""
        active_tasks = []
        cutoff_time = datetime.now() - timedelta(hours=1)
        
        for state_file in STORAGE_PATH.glob("*_state.json"):
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                
                if state.get("user_id") != user_id:
                    continue
                
                status = state.get("status")
                if status not in ["running", "created"]:
                    continue
                
                last_updated = datetime.fromisoformat(state.get("last_updated", "2000-01-01"))
                if last_updated < cutoff_time:
                    continue
                
                chunks_count = state.get("chunks_count", 0)
                progress = min(chunks_count, 100)
                
                active_tasks.append(SessionInfo(
                    task_id=state["task_id"],
                    status=status,
                    prompt=state.get("prompt", "")[:100],
                    progress=progress,
                    chunks_count=chunks_count,
                    created_at=state.get("created_at", ""),
                    last_updated=state.get("last_updated", "")
                ))
            
            except Exception as e:
                print(f"Error reading {state_file}: {e}")
                continue
        
        active_tasks.sort(key=lambda x: x.last_updated, reverse=True)
        return active_tasks
    
    @staticmethod
    def cleanup_old_tasks(hours: int = 24):
        """Nettoyer les vieilles tâches"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        cleaned = 0
        
        for state_file in STORAGE_PATH.glob("*_state.json"):
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                
                last_updated = datetime.fromisoformat(state.get("last_updated", "2000-01-01"))
                
                if last_updated < cutoff_time:
                    task_id = state["task_id"]
                    state_file.unlink()
                    chunks_file = STORAGE_PATH / f"{task_id}_chunks.json"
                    if chunks_file.exists():
                        chunks_file.unlink()
                    cleaned += 1
            except Exception as e:
                print(f"Error cleaning {state_file}: {e}")
        
        return cleaned

storage = SessionStorage()

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
    async for chunk in stream:
        if chunk.choices[0].delta.content:
            text = chunk.choices[0].delta.content
            
            storage.save_chunk(task_id, chunk_id, text, {
                "provider": "openai",
                "model": model
            })
            
            yield {
                "chunk_id": chunk_id,
                "text": text,
                "is_replay": False,
                "provider": "openai",
                "model": model
            }
            
            chunk_id += 1

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
    async with anthropic_client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}]
    ) as stream:
        async for text in stream.text_stream:
            storage.save_chunk(task_id, chunk_id, text, {
                "provider": "anthropic",
                "model": model
            })
            
            yield {
                "chunk_id": chunk_id,
                "text": text,
                "is_replay": False,
                "provider": "anthropic",
                "model": model
            }
            
            chunk_id += 1

# ==================== ENDPOINTS ====================

@app.get("/")
async def root():
    return {
        "service": "Chatbot LLM Backend - MVP with Sessions",
        "version": "2.0.0",
        "status": "running"
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "openai_configured": openai_client is not None,
        "anthropic_configured": anthropic_client is not None
    }

@app.post("/api/chat/generate", response_model=TaskResponse)
async def create_chat_task(request: ChatRequest):
    """Créer une tâche de génération"""
    
    task_id = str(uuid.uuid4())
    user_id = request.user_id or str(uuid.uuid4())
    
    model = request.model
    if not model:
        model = OPENAI_MODEL if request.provider == "openai" else ANTHROPIC_MODEL
    
    storage.save_task_state(task_id, {
        "task_id": task_id,
        "user_id": user_id,
        "status": "created",
        "provider": request.provider,
        "model": model,
        "prompt": request.prompt,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "created_at": datetime.now().isoformat(),
        "chunks_count": 0,
        "last_chunk_id": -1
    })
    
    asyncio.create_task(
        generate_background(
            task_id,
            request.prompt,
            request.provider,
            model,
            request.temperature,
            request.max_tokens
        )
    )
    
    return TaskResponse(
        task_id=task_id,
        status="running",
        provider=request.provider,
        model=model,
        user_id=user_id
    )

async def generate_background(
    task_id: str,
    prompt: str,
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int
):
    """Génération en arrière-plan"""
    
    try:
        state = storage.get_task_state(task_id)
        state["status"] = "running"
        state["started_at"] = datetime.now().isoformat()
        storage.save_task_state(task_id, state)
        
        if provider == "openai":
            async for _ in stream_openai(prompt, task_id, model, temperature, max_tokens):
                pass
        else:
            async for _ in stream_anthropic(prompt, task_id, model, temperature, max_tokens):
                pass
        
        state = storage.get_task_state(task_id)
        state["status"] = "completed"
        state["completed_at"] = datetime.now().isoformat()
        storage.save_task_state(task_id, state)
    
    except Exception as e:
        state = storage.get_task_state(task_id)
        state["status"] = "error"
        state["error"] = str(e)
        state["failed_at"] = datetime.now().isoformat()
        storage.save_task_state(task_id, state)

@app.get("/api/chat/status/{task_id}")
async def get_task_status(task_id: str):
    """Obtenir status d'une tâche"""
    state = storage.get_task_state(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")
    return state

@app.get("/api/chat/chunks/{task_id}")
async def get_chunks(task_id: str, from_id: int = 0):
    """Récupérer chunks d'une tâche"""
    chunks = storage.get_chunks(task_id, from_id)
    return {
        "task_id": task_id,
        "chunks": chunks,
        "total": len(chunks)
    }

# ==================== SESSION ENDPOINTS ====================

@app.get("/api/sessions/{user_id}/active")
async def get_active_sessions(user_id: str):
    """Récupérer les tâches actives d'un utilisateur"""
    active_tasks = storage.get_user_active_tasks(user_id)
    return {
        "user_id": user_id,
        "active_tasks": [task.dict() for task in active_tasks],
        "count": len(active_tasks)
    }

@app.post("/api/sessions/cleanup")
async def cleanup_sessions(hours: int = 24):
    """Nettoyer les sessions anciennes"""
    cleaned = storage.cleanup_old_tasks(hours)
    return {
        "cleaned": cleaned,
        "message": f"Cleaned {cleaned} old tasks (>{hours}h)"
    }

# ==================== STARTUP ====================

@app.on_event("startup")
async def startup():
    print("=" * 60)
    print("🚀 Backend MVP with Sessions Started")
    print("=" * 60)
    print(f"   OpenAI configured: {openai_client is not None}")
    print(f"   Anthropic configured: {anthropic_client is not None}")
    print(f"   Storage: {STORAGE_PATH}")
    
    # Cleanup old tasks
    cleaned = storage.cleanup_old_tasks(hours=24)
    if cleaned > 0:
        print(f"   Cleaned {cleaned} old tasks")
    print("=" * 60)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)