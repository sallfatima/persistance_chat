"""
Worker Temporal
Exécute les workflows et activities
"""

import asyncio
import os
from temporalio.client import Client
from temporalio.worker import Worker
import logging

# Import workflows et activities
from workflows import ChatStreamingWorkflow, BatchChatWorkflow
from activities import (
    validate_prompt,
    generate_full_text_with_llm,
    save_chunk_to_storage,
    notify_frontend,
    get_chunks_from_storage,
    cleanup_old_workflows
)

# ==================== CONFIGURATION ====================

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "temporal")
TEMPORAL_PORT = int(os.getenv("TEMPORAL_PORT", 7233))
TASK_QUEUE = os.getenv("TASK_QUEUE", "chatbot-task-queue")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== WORKER ====================

async def main():
    """
    Démarrer le worker Temporal
    
    Le worker:
    1. Se connecte au serveur Temporal
    2. Écoute sur une task queue
    3. Exécute workflows et activities
    4. Checkpoint automatique
    """
    
    logger.info("🚀 Starting Temporal Worker...")
    logger.info(f"   Temporal Server: {TEMPORAL_HOST}:{TEMPORAL_PORT}")
    logger.info(f"   Task Queue: {TASK_QUEUE}")
    
    # Connexion au serveur Temporal
    try:
        client = await Client.connect(
            f"{TEMPORAL_HOST}:{TEMPORAL_PORT}",
            namespace="default"
        )
        logger.info("✅ Connected to Temporal Server")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Temporal: {e}")
        return
    
    # Créer worker
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[
            ChatStreamingWorkflow,
            BatchChatWorkflow
        ],
        activities=[
            validate_prompt,
            generate_full_text_with_llm,
            save_chunk_to_storage,
            notify_frontend,
            get_chunks_from_storage,
            cleanup_old_workflows
        ],
        max_concurrent_activities=10,
        max_concurrent_workflow_tasks=10
    )
    
    logger.info("✅ Worker created")
    logger.info("📋 Registered workflows:")
    logger.info("   - ChatStreamingWorkflow")
    logger.info("   - BatchChatWorkflow")
    logger.info("📋 Registered activities:")
    logger.info("   - validate_prompt")
    logger.info("   - generate_full_text_with_llm")
    logger.info("   - save_chunk_to_storage")
    logger.info("   - notify_frontend")
    logger.info("   - get_chunks_from_storage")
    logger.info("   - cleanup_old_workflows")
    
    logger.info("🎯 Worker listening for tasks...")
    
    # Démarrer le worker (bloquant)
    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("⚠️  Worker interrupted by user")
    except Exception as e:
        logger.error(f"❌ Worker error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
