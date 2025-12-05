"""
Backend FastAPI pour Solution 3 (MVP)
Full LangChain (OpenAI + Anthropic) + Sessions persistantes
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

import os
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator, Optional, List
import asyncio

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ==================== CONFIGURATION ====================

app = FastAPI(
    title="Chatbot LLM Backend - MVP with Sessions (LangChain)",
    description="Backend avec gestion de sessions utilisateur et streaming",
    version="3.0.0",
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

STORAGE_PATH.mkdir(parents=True, exist_ok=True)

OPENAI_CONFIGURED = bool(OPENAI_API_KEY)
ANTHROPIC_CONFIGURED = bool(ANTHROPIC_API_KEY)

# ==================== Pydantic Models ====================

class ChatRequest(BaseModel):
    prompt: str
    provider: str = "openai"     # "openai" | "anthropic"
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

# ==================== STORAGE ====================

class SessionStorage:
    """Stockage avec gestion de sessions utilisateur"""

    @staticmethod
    def _state_path(task_id: str) -> Path:
        return STORAGE_PATH / f"{task_id}_state.json"

    @staticmethod
    def _chunks_path(task_id: str) -> Path:
        return STORAGE_PATH / f"{task_id}_chunks.json"

    @staticmethod
    def save_task_state(task_id: str, state: dict):
        """Sauvegarder état de tâche"""
        file_path = SessionStorage._state_path(task_id)
        state["last_updated"] = datetime.now().isoformat()
        with open(file_path, "w") as f:
            json.dump(state, f, indent=2)

    @staticmethod
    def get_task_state(task_id: str) -> Optional[dict]:
        file_path = SessionStorage._state_path(task_id)
        if file_path.exists():
            with open(file_path, "r") as f:
                return json.load(f)
        return None

    @staticmethod
    def save_chunk(task_id: str, chunk_id: int, text: str, metadata: dict):
        """Sauvegarder un chunk"""
        file_path = SessionStorage._chunks_path(task_id)

        chunks = []
        if file_path.exists():
            with open(file_path, "r") as f:
                chunks = json.load(f)

        chunks.append(
            {
                "chunk_id": chunk_id,
                "text": text,
                "timestamp": datetime.now().isoformat(),
                **metadata,
            }
        )

        with open(file_path, "w") as f:
            json.dump(chunks, f, indent=2)

        state = SessionStorage.get_task_state(task_id)
        if state:
            state["last_chunk_id"] = chunk_id
            state["chunks_count"] = len(chunks)
            SessionStorage.save_task_state(task_id, state)

    @staticmethod
    def get_chunks(task_id: str, from_id: int = 0) -> List[dict]:
        file_path = SessionStorage._chunks_path(task_id)
        if file_path.exists():
            with open(file_path, "r") as f:
                chunks = json.load(f)
            return [c for c in chunks if c["chunk_id"] >= from_id]
        return []

    @staticmethod
    def get_user_recent_tasks(user_id: str, hours: int = 24) -> List[SessionInfo]:
        """
        Récupérer les tâches RÉCENTES d'un utilisateur
        (inclut running, created, completed)
        """
        recent_tasks: List[SessionInfo] = []
        cutoff_time = datetime.now() - timedelta(hours=hours)

        for state_file in STORAGE_PATH.glob("*_state.json"):
            try:
                with open(state_file, "r") as f:
                    state = json.load(f)

                if state.get("user_id") != user_id:
                    continue

                status = state.get("status")
                if status not in ["running", "created", "completed"]:
                    continue

                last_updated_str = state.get("last_updated", "2000-01-01")
                last_updated = datetime.fromisoformat(last_updated_str)
                if last_updated < cutoff_time:
                    continue

                chunks_count = state.get("chunks_count", 0)
                # estimation simple = chunks_count (max arbitraire 100)
                progress = min(chunks_count, 100.0)

                recent_tasks.append(
                    SessionInfo(
                        task_id=state["task_id"],
                        status=status,
                        prompt=state.get("prompt", "")[:100],
                        progress=progress,
                        chunks_count=chunks_count,
                        created_at=state.get("created_at", ""),
                        last_updated=last_updated_str,
                    )
                )

            except Exception as e:
                print(f"[WARN] Error reading {state_file}: {e}")
                continue

        recent_tasks.sort(key=lambda x: x.last_updated, reverse=True)
        return recent_tasks

    @staticmethod
    def cleanup_old_tasks(hours: int = 24) -> int:
        cutoff_time = datetime.now() - timedelta(hours=hours)
        cleaned = 0

        for state_file in STORAGE_PATH.glob("*_state.json"):
            try:
                with open(state_file, "r") as f:
                    state = json.load(f)

                last_updated = datetime.fromisoformat(
                    state.get("last_updated", "2000-01-01")
                )
                if last_updated < cutoff_time:
                    task_id = state["task_id"]
                    state_file.unlink(missing_ok=True)
                    SessionStorage._chunks_path(task_id).unlink(missing_ok=True)
                    cleaned += 1
            except Exception as e:
                print(f"[WARN] Error cleaning {state_file}: {e}")

        return cleaned


storage = SessionStorage()

# ==================== LLM STREAMING (LangChain) ====================

async def stream_openai(
    prompt: str,
    task_id: str,
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 4000,
) -> AsyncIterator[dict]:
    if not OPENAI_CONFIGURED:
        raise HTTPException(status_code=500, detail="OpenAI not configured")

    llm = ChatOpenAI(
        model=model,
        api_key=OPENAI_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=True,
    )

    chunk_id = 0
    async for chunk in llm.astream(prompt):
        if not chunk.content:
            continue

        text = chunk.content

        storage.save_chunk(
            task_id,
            chunk_id,
            text,
            {"provider": "openai", "model": model},
        )

        yield {
            "chunk_id": chunk_id,
            "text": text,
            "is_replay": False,
            "provider": "openai",
            "model": model,
        }

        chunk_id += 1


async def stream_anthropic(
    prompt: str,
    task_id: str,
    model: str = "claude-3-5-sonnet-20241022",
    temperature: float = 0.7,
    max_tokens: int = 4000,
) -> AsyncIterator[dict]:
    if not ANTHROPIC_CONFIGURED:
        raise HTTPException(status_code=500, detail="Anthropic not configured")

    llm = ChatAnthropic(
        model=model,
        api_key=ANTHROPIC_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=True,
    )

    chunk_id = 0
    async for chunk in llm.astream(prompt):
        if not chunk.content:
            continue

        text = chunk.content

        storage.save_chunk(
            task_id,
            chunk_id,
            text,
            {"provider": "anthropic", "model": model},
        )

        yield {
            "chunk_id": chunk_id,
            "text": text,
            "is_replay": False,
            "provider": "anthropic",
            "model": model,
        }

        chunk_id += 1


# ==================== ENDPOINTS ====================

@app.get("/")
async def root():
    return {
        "service": "Chatbot LLM Backend - LangChain Sessions",
        "version": "3.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "openai_configured": OPENAI_CONFIGURED,
        "anthropic_configured": ANTHROPIC_CONFIGURED,
    }


@app.post("/api/chat/generate", response_model=TaskResponse)
async def create_chat_task(request: ChatRequest):
    task_id = str(uuid.uuid4())
    user_id = request.user_id or str(uuid.uuid4())

    model = request.model
    if not model:
        model = OPENAI_MODEL if request.provider == "openai" else ANTHROPIC_MODEL

    storage.save_task_state(
        task_id,
        {
            "task_id": task_id,
            "user_id": user_id,
            "status": "created",
            "provider": request.provider,
            "model": model,
            "prompt": request.prompt,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "chunks_count": 0,
            "last_chunk_id": -1,
        },
    )

    asyncio.create_task(
        generate_background(
            task_id,
            request.prompt,
            request.provider,
            model,
            request.temperature,
            request.max_tokens,
        )
    )

    return TaskResponse(
        task_id=task_id,
        status="running",
        provider=request.provider,
        model=model,
        user_id=user_id,
    )


async def generate_background(
    task_id: str,
    prompt: str,
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int,
):
    try:
        state = storage.get_task_state(task_id) or {}
        state["status"] = "running"
        state["started_at"] = datetime.now().isoformat()
        storage.save_task_state(task_id, state)

        if provider == "openai":
            async for _ in stream_openai(prompt, task_id, model, temperature, max_tokens):
                pass
        else:
            async for _ in stream_anthropic(
                prompt, task_id, model, temperature, max_tokens
            ):
                pass

        state = storage.get_task_state(task_id) or {}
        state["status"] = "completed"
        state["completed_at"] = datetime.now().isoformat()
        storage.save_task_state(task_id, state)

    except Exception as e:
        state = storage.get_task_state(task_id) or {}
        state["status"] = "error"
        state["error"] = str(e)
        state["failed_at"] = datetime.now().isoformat()
        storage.save_task_state(task_id, state)


@app.get("/api/chat/status/{task_id}")
async def get_task_status(task_id: str):
    state = storage.get_task_state(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")
    return state


@app.get("/api/chat/chunks/{task_id}")
async def get_chunks(task_id: str, from_id: int = 0):
    chunks = storage.get_chunks(task_id, from_id)
    return {"task_id": task_id, "chunks": chunks, "total": len(chunks)}


# ==================== SESSION ENDPOINTS ====================

@app.get("/api/sessions/{user_id}/recent")
async def get_recent_sessions(user_id: str, hours: int = 24):
    """
    Récupérer les tâches RÉCENTES d'un utilisateur
    Inclut: running, created, completed
    """
    tasks = storage.get_user_recent_tasks(user_id, hours=hours)
    return {
        "user_id": user_id,
        "tasks": [task.dict() for task in tasks],
        "count": len(tasks),
    }


@app.post("/api/sessions/cleanup")
async def cleanup_sessions(hours: int = 24):
    cleaned = storage.cleanup_old_tasks(hours)
    return {"cleaned": cleaned, "message": f"Cleaned {cleaned} old tasks (>{hours}h)"}


@app.delete("/api/sessions/{user_id}/{task_id}")
async def delete_session(user_id: str, task_id: str):
    state = storage.get_task_state(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    if state.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    SessionStorage._state_path(task_id).unlink(missing_ok=True)
    SessionStorage._chunks_path(task_id).unlink(missing_ok=True)
    return {"message": "Session deleted"}


# ==================== WEBSOCKET (replay temps réel) ====================

@app.websocket("/ws/chat/{task_id}")
async def websocket_chat(websocket: WebSocket, task_id: str):
    await websocket.accept()
    try:
        existing_chunks = storage.get_chunks(task_id)
        for chunk in existing_chunks:
            await websocket.send_json({**chunk, "is_replay": True})
            await asyncio.sleep(0.01)

        last_chunk_id = len(existing_chunks)

        while True:
            state = storage.get_task_state(task_id)
            if not state:
                break

            new_chunks = storage.get_chunks(task_id, last_chunk_id)
            for chunk in new_chunks:
                await websocket.send_json({**chunk, "is_replay": False})
                last_chunk_id = chunk["chunk_id"] + 1

            if state.get("status") in ["completed", "error"]:
                await websocket.send_json({"done": True, "status": state.get("status")})
                break

            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        pass


# ==================== STARTUP ====================

@app.on_event("startup")
async def startup():
    print("🚀 Backend LangChain with Sessions Started")
    print(f"   OpenAI configured: {OPENAI_CONFIGURED}")
    print(f"   Anthropic configured: {ANTHROPIC_CONFIGURED}")
    print(f"   Storage: {STORAGE_PATH}")
    cleaned = storage.cleanup_old_tasks(hours=48)
    if cleaned:
        print(f"   Cleaned {cleaned} old tasks")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
