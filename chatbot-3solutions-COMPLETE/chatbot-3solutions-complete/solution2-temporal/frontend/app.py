"""
Frontend Chainlit pour Solution 2 (Temporal)
Affiche le progrès des workflows avec monitoring temps réel
"""

import chainlit as cl
import httpx
import asyncio
import os
from typing import Optional
from datetime import datetime

# ==================== CONFIGURATION ====================

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Modèles disponibles
OPENAI_MODELS = {
    "gpt-4o": "GPT-4o (Recommandé)",
    "gpt-4o-mini": "GPT-4o Mini (Économique)"
}

ANTHROPIC_MODELS = {
    "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet (Recommandé)",
    "claude-3-haiku-20240307": "Claude 3 Haiku (Économique)"
}

# ==================== HELPERS ====================

async def check_backend_health() -> dict:
    """Vérifier santé du backend"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BACKEND_URL}/health", timeout=5.0)
            return response.json()
    except Exception as e:
        return {"status": "error", "error": str(e)}

async def start_workflow(prompt: str, provider: str, model: str, temperature: float) -> dict:
    """Démarrer un workflow Temporal"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BACKEND_URL}/api/workflows/start",
            json={
                "prompt": prompt,
                "provider": provider,
                "model": model,
                "temperature": temperature
            },
            timeout=10.0
        )
        return response.json()

async def get_workflow_status(workflow_id: str) -> dict:
    """Obtenir status workflow"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BACKEND_URL}/api/workflows/{workflow_id}/status",
            timeout=5.0
        )
        return response.json()

async def get_workflow_chunks(workflow_id: str) -> dict:
    """Obtenir chunks workflow"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BACKEND_URL}/api/workflows/{workflow_id}/chunks",
            timeout=5.0
        )
        return response.json()

async def stream_workflow_progress(workflow_id: str, msg: cl.Message):
    """
    Stream le progrès du workflow avec monitoring
    
    Affiche:
    - Barre de progression
    - Status actuel
    - Chunks au fur et à mesure
    """
    
    start_time = datetime.now()
    last_chunk_count = 0
    last_status = ""
    
    # Barre de progression
    progress_msg = "⏳ **Workflow en cours...**\n\n"
    await msg.stream_token(progress_msg)
    
    while True:
        # Récupérer status
        try:
            status = await get_workflow_status(workflow_id)
        except Exception as e:
            await msg.stream_token(f"\n\n❌ Error getting status: {e}")
            break
        
        current_status = status.get("status", "unknown")
        progress = status.get("progress", 0)
        chunks_count = status.get("chunks_count", 0)
        total_chunks = status.get("total_chunks", 0)
        
        # Afficher changement de status
        if current_status != last_status:
            status_emoji = {
                "started": "🚀",
                "validating": "🔍",
                "generating": "🤖",
                "chunking": "✂️",
                "saving": "💾",
                "completed": "✅",
                "error": "❌",
                "cancelled": "🚫"
            }.get(current_status, "⏳")
            
            await msg.stream_token(f"\n\n{status_emoji} **{current_status.upper()}**\n")
            last_status = current_status
        
        # Afficher nouveaux chunks
        if chunks_count > last_chunk_count:
            try:
                chunks_data = await get_workflow_chunks(workflow_id)
                new_chunks = chunks_data["chunks"][last_chunk_count:]
                
                for chunk in new_chunks:
                    await msg.stream_token(chunk["text"])
                
                last_chunk_count = chunks_count
            except:
                pass
        
        # Afficher progression
        if total_chunks > 0 and progress > 0:
            bar_length = 20
            filled = int(bar_length * progress / 100)
            bar = "█" * filled + "░" * (bar_length - filled)
            # On n'affiche pas la barre pour éviter spam, juste dans status
        
        # Check si terminé
        if current_status == "completed":
            elapsed = (datetime.now() - start_time).total_seconds()
            
            await msg.stream_token("\n\n---\n\n")
            await msg.stream_token(f"✅ **Workflow terminé !**\n\n")
            await msg.stream_token(f"⏱️ Temps total: {elapsed:.2f}s\n")
            await msg.stream_token(f"📊 Chunks traités: {total_chunks}\n")
            await msg.stream_token(f"🔗 Workflow ID: `{workflow_id}`\n\n")
            await msg.stream_token(f"💡 **Astuce**: Ce workflow est sauvegardé dans Temporal.\n")
            await msg.stream_token(f"Même si le worker crashait, il reprendrait exactement où il était !\n\n")
            await msg.stream_token(f"🌐 Voir dans Temporal UI: http://localhost:8080")
            
            break
        
        if current_status == "error":
            error_msg = status.get("error", "Unknown error")
            await msg.stream_token(f"\n\n❌ **Error**: {error_msg}")
            break
        
        if current_status == "cancelled":
            await msg.stream_token("\n\n🚫 **Workflow annulé**")
            break
        
        await asyncio.sleep(1.0)  # Poll toutes les secondes

# ==================== CHAINLIT HANDLERS ====================

@cl.on_chat_start
async def start():
    """Initialisation de la conversation"""
    
    # Vérifier backend
    health = await check_backend_health()
    
    if health.get("status") == "error":
        await cl.Message(
            content=f"❌ **Backend inaccessible**\n\n"
                    f"Erreur: {health.get('error')}\n\n"
                    f"Assurez-vous que le backend tourne sur {BACKEND_URL}"
        ).send()
        return
    
    # Créer settings
    settings = await cl.ChatSettings(
        [
            cl.input_widget.Select(
                id="Provider",
                label="🤖 LLM Provider",
                values=["OpenAI GPT", "Anthropic Claude"],
                initial_value="OpenAI GPT"
            ),
            cl.input_widget.Select(
                id="Model",
                label="📦 Modèle",
                values=list(OPENAI_MODELS.keys()),
                initial_value="gpt-4o"
            ),
            cl.input_widget.Slider(
                id="Temperature",
                label="🌡️ Température",
                initial=0.7,
                min=0.0,
                max=2.0,
                step=0.1
            )
        ]
    ).send()
    
    # Init session
    cl.user_session.set("provider", "openai")
    cl.user_session.set("model", "gpt-4o")
    cl.user_session.set("temperature", 0.7)
    
    # Message de bienvenue
    welcome_msg = "# 🟣 Chatbot LLM - Temporal Workflows\n\n"
    welcome_msg += "## Architecture Enterprise\n\n"
    welcome_msg += "```\n"
    welcome_msg += "Chainlit → FastAPI → Temporal Server → Workers → GPT/Claude\n"
    welcome_msg += "```\n\n"
    
    welcome_msg += "## Backend Status\n\n"
    welcome_msg += f"- Temporal: {'🟢 Connecté' if health.get('temporal_connected') else '🔴 Déconnecté'}\n"
    welcome_msg += f"- Server: {health.get('temporal_server', 'N/A')}\n"
    welcome_msg += f"- Task Queue: {health.get('task_queue', 'N/A')}\n\n"
    
    welcome_msg += "## ⚡ Avantages Temporal\n\n"
    welcome_msg += "1. **Checkpointing automatique** : Le workflow sauvegarde son état après chaque étape\n"
    welcome_msg += "2. **Reprise auto sur crash** : Si le worker crash, le workflow reprend exactement où il était\n"
    welcome_msg += "3. **Event sourcing** : Historique complet de toutes les exécutions\n"
    welcome_msg += "4. **Temporal UI** : Monitoring visuel sur http://localhost:8080\n\n"
    
    welcome_msg += "## 🧪 Test Crash Recovery\n\n"
    welcome_msg += "Pour tester la résilience:\n"
    welcome_msg += "1. Lancez une génération longue\n"
    welcome_msg += "2. Pendant la génération: `docker-compose stop worker`\n"
    welcome_msg += "3. Attendez 30 secondes\n"
    welcome_msg += "4. Relancez: `docker-compose start worker`\n"
    welcome_msg += "5. ✅ Le workflow reprend EXACTEMENT où il était !\n\n"
    
    welcome_msg += "💬 Envoyez un message pour démarrer un workflow !"
    
    await cl.Message(content=welcome_msg).send()

@cl.on_settings_update
async def update_settings(settings):
    """Mise à jour des paramètres"""
    
    provider_name = settings["Provider"]
    model = settings["Model"]
    temperature = settings["Temperature"]
    
    provider = "openai" if provider_name == "OpenAI GPT" else "anthropic"
    
    cl.user_session.set("provider", provider)
    cl.user_session.set("model", model)
    cl.user_session.set("temperature", temperature)
    
    await cl.Message(
        content=f"✅ **Configuration mise à jour**\n\n"
                f"- Provider: {provider_name}\n"
                f"- Modèle: {model}\n"
                f"- Température: {temperature}"
    ).send()

@cl.on_message
async def main(message: cl.Message):
    """Traitement du message"""
    
    # Récupérer config
    provider = cl.user_session.get("provider", "openai")
    model = cl.user_session.get("model", "gpt-4o")
    temperature = cl.user_session.get("temperature", 0.7)
    
    # Message de réponse
    msg = cl.Message(content="")
    
    # ✅ FIX: Initialize workflow_id to None
    workflow_id = None
    
    try:
        # Afficher info provider
        provider_name = "OpenAI GPT" if provider == "openai" else "Anthropic Claude"
        await msg.stream_token(f"🤖 **{provider_name}** - {model}\n")
        await msg.stream_token(f"🌡️ Température: {temperature}\n\n")
        
        # Démarrer workflow
        workflow_data = await start_workflow(
            message.content,
            provider,
            model,
            temperature
        )
        
        workflow_id = workflow_data["workflow_id"]
        run_id = workflow_data.get("run_id", "N/A")
        
        await msg.stream_token(f"🆔 Workflow ID: `{workflow_id}`\n")
        await msg.stream_token(f"🏃 Run ID: `{run_id}`\n\n")
        await msg.stream_token("---\n\n")
        
        # Stream progrès
        await stream_workflow_progress(workflow_id, msg)
    
    except Exception as e:
        await msg.stream_token(f"\n\n❌ **Erreur**: {str(e)}")
    
    # Envoyer
    await msg.send()
    
    # ✅ FIX: Only set workflow_id if it exists
    msg.metadata = {
        "provider": provider,
        "model": model,
        "temperature": temperature
    }
    
    if workflow_id:
        msg.metadata["workflow_id"] = workflow_id
    
    await msg.update()

# ==================== PROFILS DE CHAT ====================

@cl.set_chat_profiles
async def chat_profile():
    """Définir profils de chat"""
    
    return [
        cl.ChatProfile(
            name="Temporal-Resilient",
            markdown_description="**Workflows Temporal** avec crash recovery automatique",
            icon="⚡"
        ),
        cl.ChatProfile(
            name="Temporal-Batch",
            markdown_description="**Traitement batch** - Multiple prompts en parallèle",
            icon="🔀"
        )
    ]