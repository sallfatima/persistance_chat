"""
Backend FastAPI pour Solution 3 (MVP)
Streaming LLM avec OpenAI GPT et Anthropic Claude
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Header
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
from langchain_openai import ChatOpenAI

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))


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
STORAGE_PATH = Path(os.getenv("STORAGE_PATH", "/tmp/chatbot_storage"))

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
    user_id: Optional[str] = None  # ← NOUVEAU

class TaskResponse(BaseModel):
    task_id: str
    status: str
    provider: str
    model: str
    user_id: str  # ← NOUVEAU

class ChunkData(BaseModel):
    chunk_id: int
    text: str
    is_replay: bool = False
    provider: str
    model: str

class SessionInfo(BaseModel):
    task_id: str
    status: str
    prompt: str
    progress: float
    chunks_count: int
    created_at: str
    last_updated: str

# ==================== STORAGE WITH USER SESSIONS ====================

class SessionStorage:
    """Stockage avec gestion de sessions utilisateur"""
    
    @staticmethod
    def save_task_state(task_id: str, state: dict):
        """Sauvegarder état de tâche"""
        file_path = STORAGE_PATH / f"{task_id}_state.json"
        
        # Ajouter timestamp
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
        
        # Charger chunks existants
        chunks = []
        if file_path.exists():
            with open(file_path, 'r') as f:
                chunks = json.load(f)
        
        # Ajouter nouveau chunk
        chunks.append({
            "chunk_id": chunk_id,
            "text": text,
            "timestamp": datetime.now().isoformat(),
            **metadata
        })
        
        # Sauvegarder
        with open(file_path, 'w') as f:
            json.dump(chunks, f, indent=2)
        
        # Mettre à jour le state avec le progress
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
        """
        Récupérer toutes les tâches actives d'un utilisateur
        Une tâche est considérée active si:
        - status = "running" OU "created"
        - Dernière mise à jour < 1 heure
        """
        active_tasks = []
        cutoff_time = datetime.now() - timedelta(hours=1)
        
        # Parcourir tous les fichiers state
        for state_file in STORAGE_PATH.glob("*_state.json"):
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                
                # Vérifier si appartient à cet utilisateur
                if state.get("user_id") != user_id:
                    continue
                
                # Vérifier si encore actif
                status = state.get("status")
                if status not in ["running", "created"]:
                    continue
                
                # Vérifier timestamp
                last_updated = datetime.fromisoformat(state.get("last_updated", "2000-01-01"))
                if last_updated < cutoff_time:
                    continue
                
                # Calculer progress
                chunks_count = state.get("chunks_count", 0)
                progress = chunks_count / 100 * 100  # Estimation
                
                active_tasks.append(SessionInfo(
                    task_id=state["task_id"],
                    status=status,
                    prompt=state.get("prompt", "")[:100],  # Tronquer
                    progress=min(progress, 100),
                    chunks_count=chunks_count,
                    created_at=state.get("created_at", ""),
                    last_updated=state.get("last_updated", "")
                ))
            
            except Exception as e:
                print(f"Error reading {state_file}: {e}")
                continue
        
        # Trier par date (plus récent en premier)
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
                    
                    # Supprimer state et chunks
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
):
    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=True,
        api_key=OPENAI_API_KEY
    )

    chunk_id = 0

    async for chunk in llm.astream(prompt):
        if chunk.content:
            text = chunk.content

            # Save
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
            # Sauvegarder chunk
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
    """Root endpoint"""
    return {
        "service": "Chatbot LLM Backend - MVP with Sessions",
        "version": "2.0.0",
        "status": "running"
    }

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "openai_configured": openai_client is not None,
        "anthropic_configured": anthropic_client is not None
    }

@app.post("/api/chat/generate", response_model=TaskResponse)
async def create_chat_task(request: ChatRequest):
    """
    Créer une tâche de génération
    
    Nouveau: Associe la tâche à un user_id
    """
    
    # Générer task ID
    task_id = str(uuid.uuid4())
    
    # Générer ou récupérer user_id
    user_id = request.user_id or str(uuid.uuid4())
    
    # Déterminer modèle
    model = request.model
    if not model:
        model = OPENAI_MODEL if request.provider == "openai" else ANTHROPIC_MODEL
    
    # Sauvegarder état initial
    storage.save_task_state(task_id, {
        "task_id": task_id,
        "user_id": user_id,  # ← NOUVEAU
        "status": "created",
        "provider": request.provider,
        "model": model,
        "prompt": request.prompt,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "created_at": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
        "chunks_count": 0,
        "last_chunk_id": -1
    })
    
    # Démarrer génération en arrière-plan
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
        # Update status
        state = storage.get_task_state(task_id)
        state["status"] = "running"
        state["started_at"] = datetime.now().isoformat()
        storage.save_task_state(task_id, state)
        
        # Stream
        if provider == "openai":
            async for _ in stream_openai(prompt, task_id, model, temperature, max_tokens):
                pass
        else:
            async for _ in stream_anthropic(prompt, task_id, model, temperature, max_tokens):
                pass
        
        # Completed
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

# ==================== SESSION ENDPOINTS (NOUVEAU) ====================

@app.get("/api/sessions/{user_id}/active")
async def get_active_sessions(user_id: str):
    """
    Récupérer les tâches actives d'un utilisateur
    
    Returns:
        Liste des tâches avec status "running" ou "created"
        et mises à jour dans la dernière heure
    """
    
    active_tasks = storage.get_user_active_tasks(user_id)
    
    return {
        "user_id": user_id,
        "active_tasks": [task.dict() for task in active_tasks],
        "count": len(active_tasks)
    }

@app.post("/api/sessions/cleanup")
async def cleanup_sessions(hours: int = 24):
    """
    Nettoyer les sessions anciennes
    
    Args:
        hours: Supprimer les sessions plus vieilles que X heures
    """
    
    cleaned = storage.cleanup_old_tasks(hours)
    
    return {
        "cleaned": cleaned,
        "message": f"Cleaned {cleaned} old tasks (>{hours}h)"
    }

@app.delete("/api/sessions/{user_id}/{task_id}")
async def delete_session(user_id: str, task_id: str):
    """
    Supprimer une session spécifique
    """
    
    state = storage.get_task_state(task_id)
    
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if state.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Supprimer fichiers
    state_file = STORAGE_PATH / f"{task_id}_state.json"
    chunks_file = STORAGE_PATH / f"{task_id}_chunks.json"
    
    if state_file.exists():
        state_file.unlink()
    
    if chunks_file.exists():
        chunks_file.unlink()
    
    return {"message": "Session deleted"}

# ==================== WEBSOCKET (optionnel) ====================

@app.websocket("/ws/chat/{task_id}")
async def websocket_chat(websocket: WebSocket, task_id: str):
    """WebSocket pour streaming temps réel"""
    
    await websocket.accept()
    
    try:
        # Replay chunks existants
        existing_chunks = storage.get_chunks(task_id)
        for chunk in existing_chunks:
            await websocket.send_json({
                **chunk,
                "is_replay": True
            })
            await asyncio.sleep(0.01)
        
        # Stream nouveaux chunks
        last_chunk_id = len(existing_chunks)
        
        while True:
            state = storage.get_task_state(task_id)
            if not state:
                break
            
            new_chunks = storage.get_chunks(task_id, last_chunk_id)
            for chunk in new_chunks:
                await websocket.send_json({
                    **chunk,
                    "is_replay": False
                })
                last_chunk_id = chunk['chunk_id'] + 1
            
            if state.get('status') == 'completed':
                await websocket.send_json({"done": True})
                break
            
            if state.get('status') == 'error':
                await websocket.send_json({
                    "error": state.get('error'),
                    "done": True
                })
                break
            
            await asyncio.sleep(0.1)
    
    except WebSocketDisconnect:
        pass

# ==================== STARTUP ====================

@app.on_event("startup")
async def startup():
    print("🚀 Backend MVP with Sessions Started")
    print(f"   OpenAI configured: {openai_client is not None}")
    print(f"   Anthropic configured: {anthropic_client is not None}")
    print(f"   Storage: {STORAGE_PATH}")
    
    # Cleanup old tasks au démarrage
    cleaned = storage.cleanup_old_tasks(hours=24)
    if cleaned > 0:
        print(f"   Cleaned {cleaned} old tasks")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)