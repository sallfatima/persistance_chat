"""
Backend FastAPI pour Solution 3 (MVP)
Streaming LLM avec OpenAI GPT et Anthropic Claude
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional, List
import asyncio

# ==================== CONFIGURATION ====================

app = FastAPI(
    title="Chatbot LLM Backend - MVP",
    description="Backend pour streaming LLM avec GPT et Claude",
    version="1.0.0"
)

# CORS pour Chainlit
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
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

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

class ChunkData(BaseModel):
    chunk_id: int
    text: str
    is_replay: bool = False
    provider: str
    model: str

# ==================== STORAGE ====================

class SimpleStorage:
    """Stockage simple avec fichiers JSON"""
    
    @staticmethod
    def save_task_state(task_id: str, state: dict):
        """Sauvegarder état de tâche"""
        file_path = STORAGE_PATH / f"{task_id}_state.json"
        with open(file_path, 'w') as f:
            json.dump(state, f)
    
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
            json.dump(chunks, f)
    
    @staticmethod
    def get_chunks(task_id: str, from_id: int = 0) -> List[dict]:
        """Récupérer chunks depuis un ID"""
        file_path = STORAGE_PATH / f"{task_id}_chunks.json"
        if file_path.exists():
            with open(file_path, 'r') as f:
                chunks = json.load(f)
            return [c for c in chunks if c['chunk_id'] >= from_id]
        return []

storage = SimpleStorage()

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
            
            # Sauvegarder chunk
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
        "service": "Chatbot LLM Backend - MVP",
        "version": "1.0.0",
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
    
    Returns:
        task_id pour suivre la génération
    """
    
    # Générer task ID
    task_id = str(uuid.uuid4())
    
    # Déterminer modèle
    model = request.model
    if not model:
        model = OPENAI_MODEL if request.provider == "openai" else ANTHROPIC_MODEL
    
    # Sauvegarder état initial
    storage.save_task_state(task_id, {
        "status": "created",
        "provider": request.provider,
        "model": model,
        "prompt": request.prompt,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "created_at": datetime.now().isoformat()
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
        model=model
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
        storage.save_task_state(task_id, {
            "status": "running",
            "provider": provider,
            "model": model,
            "started_at": datetime.now().isoformat()
        })
        
        # Stream
        if provider == "openai":
            async for _ in stream_openai(prompt, task_id, model, temperature, max_tokens):
                pass
        else:
            async for _ in stream_anthropic(prompt, task_id, model, temperature, max_tokens):
                pass
        
        # Completed
        storage.save_task_state(task_id, {
            "status": "completed",
            "provider": provider,
            "model": model,
            "completed_at": datetime.now().isoformat()
        })
    
    except Exception as e:
        storage.save_task_state(task_id, {
            "status": "error",
            "error": str(e),
            "failed_at": datetime.now().isoformat()
        })

@app.get("/api/chat/status/{task_id}")
async def get_task_status(task_id: str):
    """Obtenir status d'une tâche"""
    
    state = storage.get_task_state(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return state

@app.websocket("/ws/chat/{task_id}")
async def websocket_chat(websocket: WebSocket, task_id: str):
    """
    WebSocket pour streaming temps réel
    
    Flow:
    1. Replay chunks existants (bleu)
    2. Stream nouveaux chunks (vert)
    """
    
    await websocket.accept()
    
    try:
        # 1. Replay chunks existants
        existing_chunks = storage.get_chunks(task_id)
        for chunk in existing_chunks:
            await websocket.send_json({
                **chunk,
                "is_replay": True
            })
            await asyncio.sleep(0.01)  # Throttle
        
        # 2. Stream nouveaux chunks
        last_chunk_id = len(existing_chunks)
        
        while True:
            # Check status
            state = storage.get_task_state(task_id)
            if not state:
                break
            
            # Get new chunks
            new_chunks = storage.get_chunks(task_id, last_chunk_id)
            for chunk in new_chunks:
                await websocket.send_json({
                    **chunk,
                    "is_replay": False
                })
                last_chunk_id = chunk['chunk_id'] + 1
            
            # Check if completed
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

@app.get("/api/chat/chunks/{task_id}")
async def get_chunks(task_id: str, from_id: int = 0):
    """Récupérer chunks d'une tâche"""
    
    chunks = storage.get_chunks(task_id, from_id)
    return {
        "task_id": task_id,
        "chunks": chunks,
        "total": len(chunks)
    }

# ==================== STARTUP ====================

@app.on_event("startup")
async def startup():
    print("🚀 Backend MVP Started")
    print(f"   OpenAI configured: {openai_client is not None}")
    print(f"   Anthropic configured: {anthropic_client is not None}")
    print(f"   Storage: {STORAGE_PATH}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
