"""
Activities Temporal pour interaction avec LLMs
"""

from temporalio import activity
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
import os
import json
from pathlib import Path
from datetime import datetime

# ==================== CONFIGURATION ====================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
STORAGE_PATH = Path(os.getenv("STORAGE_PATH", "/tmp/temporal_storage"))

# Créer dossier storage
STORAGE_PATH.mkdir(parents=True, exist_ok=True)

# Clients LLM
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# ==================== ACTIVITIES ====================

@activity.defn
async def validate_prompt(prompt: str) -> bool:
    """
    Valider le prompt
    
    Rules:
    - Au moins 3 caractères
    - Pas de caractères dangereux
    """
    
    activity.logger.info(f"Validating prompt: {prompt[:50]}...")
    
    if len(prompt) < 3:
        activity.logger.warning("Prompt too short")
        return False
    
    if len(prompt) > 10000:
        activity.logger.warning("Prompt too long")
        return False
    
    # Ajouter d'autres validations si nécessaire
    
    activity.logger.info("Prompt validated")
    return True

@activity.defn
async def generate_full_text_with_llm(
    prompt: str,
    provider: str,
    model: str,
    temperature: float = 0.7
) -> str:
    """
    Générer texte complet avec LLM
    
    IMPORTANT: Cette activity génère TOUT d'un coup (pas de streaming)
    Car Temporal ne supporte pas le streaming dans activities
    
    Le streaming sera simulé côté workflow en découpant le texte
    """
    
    activity.logger.info(f"Generating with {provider} - {model}")
    
    try:
        if provider == "openai":
            if not openai_client:
                raise Exception("OpenAI not configured")
            
            activity.logger.info("Calling OpenAI API...")
            
            response = await openai_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000,
                temperature=temperature,
                stream=False  # PAS de streaming !
            )
            
            full_text = response.choices[0].message.content
            
            activity.logger.info(f"OpenAI response received: {len(full_text)} chars")
            
            return full_text
        
        elif provider == "anthropic":
            if not anthropic_client:
                raise Exception("Anthropic not configured")
            
            activity.logger.info("Calling Anthropic API...")
            
            message = await anthropic_client.messages.create(
                model=model,
                max_tokens=4000,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                stream=False  # PAS de streaming !
            )
            
            full_text = message.content[0].text
            
            activity.logger.info(f"Anthropic response received: {len(full_text)} chars")
            
            return full_text
        
        else:
            raise Exception(f"Unknown provider: {provider}")
    
    except Exception as e:
        activity.logger.error(f"LLM generation error: {e}")
        raise

@activity.defn
async def save_chunk_to_storage(
    workflow_id: str,
    chunk_id: int,
    chunk_text: str,
    provider: str,
    model: str
):
    """
    Sauvegarder un chunk dans le storage
    
    Cette activity est appelée pour chaque chunk
    Chaque appel crée un checkpoint Temporal
    """
    
    activity.logger.info(f"Saving chunk {chunk_id} for workflow {workflow_id}")
    
    # Créer dossier pour ce workflow
    workflow_dir = STORAGE_PATH / workflow_id
    workflow_dir.mkdir(parents=True, exist_ok=True)
    
    # Sauvegarder chunk
    chunk_file = workflow_dir / f"chunk_{chunk_id:04d}.json"
    
    chunk_data = {
        "chunk_id": chunk_id,
        "text": chunk_text,
        "provider": provider,
        "model": model,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    with open(chunk_file, 'w') as f:
        json.dump(chunk_data, f)
    
    activity.logger.info(f"Chunk {chunk_id} saved successfully")

@activity.defn
async def notify_frontend(
    workflow_id: str,
    current_chunk: int,
    total_chunks: int
):
    """
    Notifier le frontend du progrès
    
    Activity fire-and-forget (pas critique si échoue)
    """
    
    activity.logger.info(f"Progress: {current_chunk+1}/{total_chunks}")
    
    # Ici on pourrait envoyer à un WebSocket, Redis Pub/Sub, etc.
    # Pour MVP, on log juste

@activity.defn
async def get_chunks_from_storage(
    workflow_id: str,
    from_chunk_id: int = 0
) -> list:
    """
    Récupérer chunks depuis le storage
    
    Utilisé pour récupération après crash ou pour frontend
    """
    
    activity.logger.info(f"Getting chunks for workflow {workflow_id} from {from_chunk_id}")
    
    workflow_dir = STORAGE_PATH / workflow_id
    
    if not workflow_dir.exists():
        return []
    
    chunks = []
    chunk_files = sorted(workflow_dir.glob("chunk_*.json"))
    
    for chunk_file in chunk_files:
        with open(chunk_file, 'r') as f:
            chunk_data = json.load(f)
        
        if chunk_data["chunk_id"] >= from_chunk_id:
            chunks.append(chunk_data)
    
    activity.logger.info(f"Found {len(chunks)} chunks")
    
    return chunks

@activity.defn
async def cleanup_old_workflows(days_old: int = 7):
    """
    Nettoyer les anciens workflows
    
    Activity de maintenance à exécuter périodiquement
    """
    
    activity.logger.info(f"Cleaning up workflows older than {days_old} days")
    
    # Implémentation simplifiée
    # En production, vérifier timestamps et supprimer
    
    count = 0
    for workflow_dir in STORAGE_PATH.iterdir():
        if workflow_dir.is_dir():
            # Vérifier âge et supprimer si nécessaire
            # Pour MVP, on garde tout
            pass
    
    activity.logger.info(f"Cleaned up {count} workflows")
    
    return count

# ==================== HELPER FUNCTIONS ====================

def get_storage_stats() -> dict:
    """Obtenir statistiques storage"""
    
    total_workflows = 0
    total_chunks = 0
    
    for workflow_dir in STORAGE_PATH.iterdir():
        if workflow_dir.is_dir():
            total_workflows += 1
            total_chunks += len(list(workflow_dir.glob("chunk_*.json")))
    
    return {
        "total_workflows": total_workflows,
        "total_chunks": total_chunks,
        "storage_path": str(STORAGE_PATH)
    }
