"""
Workflows Temporal pour génération LLM
Avec checkpointing automatique et reprise sur crash
"""

from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta
import asyncio
from typing import List
from dataclasses import dataclass

# Import activities
with workflow.unsafe.imports_passed_through():
    from activities import (
        validate_prompt,
        generate_full_text_with_llm,
        save_chunk_to_storage,
        notify_frontend
    )

@dataclass
class ChunkData:
    """Données d'un chunk"""
    chunk_id: int
    text: str
    timestamp: str

@workflow.defn
class ChatStreamingWorkflow:
    """
    Workflow pour streaming LLM avec checkpointing
    
    Fonctionnalités:
    - Checkpointing automatique après chaque activity
    - Reprise auto si crash worker
    - Event sourcing complet
    - Historique dans Temporal UI
    """
    
    def __init__(self):
        self.chunks: List[ChunkData] = []
        self.status = "started"
        self.progress = 0
        self.total_chunks = 0
        self.error_message = None
    
    @workflow.run
    async def run(
        self,
        prompt: str,
        provider: str,
        model: str,
        temperature: float = 0.7
    ) -> dict:
        """
        Exécution principale du workflow
        
        Étapes:
        1. Valider prompt
        2. Générer texte complet (pas de streaming dans activity)
        3. Découper en chunks
        4. Sauvegarder chaque chunk avec checkpoint
        """
        
        workflow_id = workflow.info().workflow_id
        self.status = "validating"
        
        # ==================== ÉTAPE 1: VALIDATION ====================
        # Activity avec retry et timeout
        is_valid = await workflow.execute_activity(
            validate_prompt,
            args=[prompt],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10)
            )
        )
        
        # ← CHECKPOINT ICI
        # Si crash maintenant, workflow reprend APRÈS validation
        
        if not is_valid:
            self.status = "error"
            self.error_message = "Invalid prompt"
            return {
                "workflow_id": workflow_id,
                "status": "error",
                "error": "Invalid prompt"
            }
        
        # ==================== ÉTAPE 2: GÉNÉRATION LLM ====================
        self.status = "generating"
        
        # IMPORTANT: Activity génère TOUT d'un coup (pas de streaming)
        # Car Temporal ne supporte pas le streaming dans activities
        try:
            full_text = await workflow.execute_activity(
                generate_full_text_with_llm,
                args=[prompt, provider, model, temperature],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=5),
                    maximum_interval=timedelta(seconds=30)
                )
            )
        except Exception as e:
            self.status = "error"
            self.error_message = str(e)
            return {
                "workflow_id": workflow_id,
                "status": "error",
                "error": str(e)
            }
        
        # ← CHECKPOINT ICI
        # Si crash maintenant, on reprend APRÈS génération complète
        # On ne re-génère PAS → économie de coûts et temps !
        
        # ==================== ÉTAPE 3: DÉCOUPAGE ====================
        self.status = "chunking"
        
        # Découper en chunks de 50 caractères (simuler streaming)
        chunk_size = 50
        chunks = self._split_into_chunks(full_text, chunk_size)
        self.total_chunks = len(chunks)
        
        # ==================== ÉTAPE 4: SAUVEGARDE CHUNKS ====================
        self.status = "saving"
        
        for i, chunk_text in enumerate(chunks):
            # Sauvegarder chunk avec activity
            await workflow.execute_activity(
                save_chunk_to_storage,
                args=[workflow_id, i, chunk_text, provider, model],
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=3)
            )
            
            # ← CHECKPOINT après CHAQUE chunk
            # Si crash ici, workflow reprend au chunk i+1
            # Les chunks 0 à i sont déjà sauvegardés
            
            # Mettre à jour state (visible via query)
            self.chunks.append(ChunkData(
                chunk_id=i,
                text=chunk_text,
                timestamp=workflow.now().isoformat()
            ))
            self.progress = int((i + 1) / len(chunks) * 100)
            
            # Notifier frontend (optionnel, fire-and-forget)
            await workflow.execute_activity(
                notify_frontend,
                args=[workflow_id, i, len(chunks)],
                start_to_close_timeout=timedelta(seconds=2),
                retry_policy=RetryPolicy(maximum_attempts=1)  # Pas critique
            )
            
            # Petit délai pour simuler streaming
            await asyncio.sleep(0.05)
        
        # ==================== COMPLETED ====================
        self.status = "completed"
        
        return {
            "workflow_id": workflow_id,
            "status": "completed",
            "total_chunks": len(chunks),
            "full_text_length": len(full_text),
            "provider": provider,
            "model": model
        }
    
    @workflow.query
    def get_status(self) -> dict:
        """
        Query pour récupérer status en cours
        Appelable pendant l'exécution du workflow
        """
        return {
            "workflow_id": workflow.info().workflow_id,
            "status": self.status,
            "progress": self.progress,
            "chunks_count": len(self.chunks),
            "total_chunks": self.total_chunks,
            "error": self.error_message
        }
    
    @workflow.query
    def get_chunks(self) -> List[dict]:
        """
        Query pour récupérer tous les chunks
        """
        return [
            {
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "timestamp": chunk.timestamp
            }
            for chunk in self.chunks
        ]
    
    @workflow.signal
    def cancel(self):
        """
        Signal pour annuler le workflow
        """
        self.status = "cancelled"
    
    def _split_into_chunks(self, text: str, chunk_size: int) -> List[str]:
        """Découper texte en chunks"""
        return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

@workflow.defn
class BatchChatWorkflow:
    """
    Workflow pour traiter plusieurs prompts en parallèle
    Démonstration de la puissance de Temporal
    """
    
    @workflow.run
    async def run(
        self,
        prompts: List[str],
        provider: str,
        model: str
    ) -> dict:
        """Traiter plusieurs prompts en parallèle"""
        
        # Démarrer sous-workflows en parallèle
        handles = []
        for i, prompt in enumerate(prompts):
            handle = await workflow.start_child_workflow(
                ChatStreamingWorkflow.run,
                args=[prompt, provider, model],
                id=f"{workflow.info().workflow_id}-child-{i}"
            )
            handles.append(handle)
        
        # Attendre tous
        results = await asyncio.gather(*[h for h in handles])
        
        return {
            "workflow_id": workflow.info().workflow_id,
            "total_prompts": len(prompts),
            "results": results
        }
