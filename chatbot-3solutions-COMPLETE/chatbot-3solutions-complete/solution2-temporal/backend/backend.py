"""
Backend FastAPI pour Solution 2 (Temporal)
Agit comme client Temporal pour démarrer et interroger workflows
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from temporalio.client import Client, WorkflowHandle
from temporalio.common import RetryPolicy
import os
import uuid
from typing import Optional, List
from datetime import timedelta

# ==================== CONFIGURATION ====================

app = FastAPI(
    title="Chatbot LLM Backend - Temporal",
    description="Backend avec Temporal pour résilience et observabilité",
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
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "temporal")
TEMPORAL_PORT = int(os.getenv("TEMPORAL_PORT", 7233))
TASK_QUEUE = os.getenv("TASK_QUEUE", "chatbot-task-queue")

# Client Temporal (initialisé au startup)
temporal_client: Optional[Client] = None

# ==================== MODELS ====================

class ChatRequest(BaseModel):
    prompt: str
    provider: str = "openai"
    model: str = "gpt-4o"
    temperature: float = 0.7

class WorkflowResponse(BaseModel):
    workflow_id: str
    status: str
    run_id: str

class BatchChatRequest(BaseModel):
    prompts: List[str]
    provider: str = "openai"
    model: str = "gpt-4o"

# ==================== ENDPOINTS ====================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Chatbot LLM Backend - Temporal",
        "version": "1.0.0",
        "status": "running",
        "temporal_connected": temporal_client is not None
    }

@app.get("/health")
async def health():
    """Health check"""
    
    # Test Temporal connection
    temporal_ok = False
    try:
        if temporal_client:
            # Ping via simple query
            await temporal_client.list_workflows()
            temporal_ok = True
    except:
        pass
    
    return {
        "status": "healthy" if temporal_ok else "degraded",
        "temporal_connected": temporal_ok,
        "temporal_server": f"{TEMPORAL_HOST}:{TEMPORAL_PORT}",
        "task_queue": TASK_QUEUE
    }

@app.post("/api/workflows/start", response_model=WorkflowResponse)
async def start_workflow(request: ChatRequest):
    """
    Démarrer un workflow Temporal
    
    Le workflow:
    1. Valide le prompt
    2. Génère avec LLM
    3. Découpe en chunks
    4. Sauvegarde avec checkpoints
    
    Returns:
        workflow_id pour suivre l'exécution
    """
    
    if not temporal_client:
        raise HTTPException(status_code=500, detail="Temporal client not initialized")
    
    # Générer workflow ID unique
    workflow_id = f"chat-{uuid.uuid4()}"
    
    try:
        # Import workflow (avec imports_passed_through)
        from workflows import ChatStreamingWorkflow
        
        # Démarrer workflow
        handle = await temporal_client.start_workflow(
            ChatStreamingWorkflow.run,
            args=[request.prompt, request.provider, request.model, request.temperature],
            id=workflow_id,
            task_queue=TASK_QUEUE,
            execution_timeout=timedelta(minutes=10)
        )
        
        return WorkflowResponse(
            workflow_id=workflow_id,
            status="running",
            run_id=handle.result_run_id
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {str(e)}")

@app.get("/api/workflows/{workflow_id}/status")
async def get_workflow_status(workflow_id: str):
    """
    Obtenir le status d'un workflow
    
    Utilise workflow.query pour récupérer l'état en cours
    Sans attendre la fin du workflow
    """
    
    if not temporal_client:
        raise HTTPException(status_code=500, detail="Temporal client not initialized")
    
    try:
        # Récupérer handle du workflow
        handle = temporal_client.get_workflow_handle(workflow_id)
        
        # Query le workflow (non-bloquant)
        from workflows import ChatStreamingWorkflow
        status = await handle.query(ChatStreamingWorkflow.get_status)
        
        return status
    
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {str(e)}")

@app.get("/api/workflows/{workflow_id}/chunks")
async def get_workflow_chunks(workflow_id: str):
    """
    Obtenir les chunks d'un workflow
    
    Utilise workflow.query pour récupérer les chunks
    """
    
    if not temporal_client:
        raise HTTPException(status_code=500, detail="Temporal client not initialized")
    
    try:
        handle = temporal_client.get_workflow_handle(workflow_id)
        
        from workflows import ChatStreamingWorkflow
        chunks = await handle.query(ChatStreamingWorkflow.get_chunks)
        
        return {
            "workflow_id": workflow_id,
            "chunks": chunks,
            "total": len(chunks)
        }
    
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {str(e)}")

@app.get("/api/workflows/{workflow_id}/result")
async def get_workflow_result(workflow_id: str):
    """
    Attendre et obtenir le résultat final d'un workflow
    
    ATTENTION: Bloquant jusqu'à ce que le workflow se termine
    """
    
    if not temporal_client:
        raise HTTPException(status_code=500, detail="Temporal client not initialized")
    
    try:
        handle = temporal_client.get_workflow_handle(workflow_id)
        
        # Attendre résultat (bloquant)
        result = await handle.result()
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get result: {str(e)}")

@app.post("/api/workflows/{workflow_id}/cancel")
async def cancel_workflow(workflow_id: str):
    """
    Annuler un workflow en cours
    
    Utilise workflow.signal pour envoyer signal de cancel
    """
    
    if not temporal_client:
        raise HTTPException(status_code=500, detail="Temporal client not initialized")
    
    try:
        handle = temporal_client.get_workflow_handle(workflow_id)
        
        from workflows import ChatStreamingWorkflow
        await handle.signal(ChatStreamingWorkflow.cancel)
        
        return {"message": f"Cancel signal sent to workflow {workflow_id}"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel: {str(e)}")

@app.post("/api/batch/start", response_model=WorkflowResponse)
async def start_batch_workflow(request: BatchChatRequest):
    """
    Démarrer workflow batch (multiple prompts en parallèle)
    
    Démonstration de la puissance de Temporal
    """
    
    if not temporal_client:
        raise HTTPException(status_code=500, detail="Temporal client not initialized")
    
    workflow_id = f"batch-{uuid.uuid4()}"
    
    try:
        from workflows import BatchChatWorkflow
        
        handle = await temporal_client.start_workflow(
            BatchChatWorkflow.run,
            args=[request.prompts, request.provider, request.model],
            id=workflow_id,
            task_queue=TASK_QUEUE,
            execution_timeout=timedelta(minutes=30)
        )
        
        return WorkflowResponse(
            workflow_id=workflow_id,
            status="running",
            run_id=handle.result_run_id
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start batch: {str(e)}")

@app.get("/api/workflows/list")
async def list_workflows(limit: int = 20):
    """
    Lister les workflows récents
    """
    
    if not temporal_client:
        raise HTTPException(status_code=500, detail="Temporal client not initialized")
    
    try:
        workflows = []
        async for workflow in temporal_client.list_workflows(
            query='TaskQueue="chatbot-task-queue"'
        ):
            workflows.append({
                "workflow_id": workflow.id,
                "status": workflow.status,
                "start_time": workflow.start_time.isoformat() if workflow.start_time else None
            })
            
            if len(workflows) >= limit:
                break
        
        return {
            "workflows": workflows,
            "total": len(workflows)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list workflows: {str(e)}")

@app.get("/api/temporal-ui")
async def get_temporal_ui_url():
    """
    Retourner URL de Temporal UI
    """
    return {
        "temporal_ui_url": "http://localhost:8080",
        "message": "Ouvrez cette URL dans votre navigateur pour voir les workflows"
    }

# ==================== STARTUP/SHUTDOWN ====================

@app.on_event("startup")
async def startup():
    """Initialisation au démarrage"""
    global temporal_client
    
    print("🚀 Starting Temporal Backend...")
    print(f"   Temporal Server: {TEMPORAL_HOST}:{TEMPORAL_PORT}")
    print(f"   Task Queue: {TASK_QUEUE}")
    
    # Connexion à Temporal
    try:
        temporal_client = await Client.connect(
            f"{TEMPORAL_HOST}:{TEMPORAL_PORT}",
            namespace="default"
        )
        print("✅ Temporal client connected")
    except Exception as e:
        print(f"❌ Temporal connection failed: {e}")
        print("⚠️  Backend starting without Temporal (degraded mode)")

@app.on_event("shutdown")
async def shutdown():
    """Nettoyage à l'arrêt"""
    if temporal_client:
        # Temporal client cleanup (automatique)
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
