"""
Frontend Chainlit avec Reconnexion AUTOMATIQUE
Reprend directement la session active sans demander
"""

import chainlit as cl
import httpx
import asyncio
import os
from typing import Optional, List
from datetime import datetime
import uuid
import json
import hashlib

# ==================== CONFIGURATION ====================

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

# user_id STABLE basé sur un identifiant fixe
STABLE_USER_ID = hashlib.md5("my-stable-user-id".encode()).hexdigest()

OPENAI_MODELS = {
    "gpt-4o": "GPT-4o (Recommandé)",
    "gpt-4o-mini": "GPT-4o Mini (Économique)"
}

ANTHROPIC_MODELS = {
    "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet (Recommandé)",
    "claude-3-haiku-20240307": "Claude 3 Haiku"
}

# ==================== HELPERS ====================

async def check_backend_health() -> dict:
    """Vérifier santé du backend"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{BACKEND_URL}/health")
            return response.json()
    except Exception as e:
        return {"status": "error", "error": str(e)}

async def get_session_history(user_id: str, limit: int = 5) -> dict:
    """Récupérer TOUT l'historique récent (actif + terminé)"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            url = f"{BACKEND_URL}/api/sessions/{user_id}/history?limit={limit}"
            response = await client.get(url)
            return response.json()
    except Exception as e:
        return {"tasks": [], "count": 0}

async def create_task(prompt: str, provider: str, model: str, temperature: float, user_id: str) -> dict:
    """Créer une tâche de génération"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{BACKEND_URL}/api/chat/generate",
            json={
                "prompt": prompt,
                "provider": provider,
                "model": model,
                "temperature": temperature,
                "user_id": user_id
            }
        )
        return response.json()

async def get_task_status(task_id: str) -> dict:
    """Récupérer le status d'une tâche"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{BACKEND_URL}/api/chat/status/{task_id}")
        return response.json()

async def get_chunks(task_id: str, from_id: int = 0) -> dict:
    """Récupérer les chunks d'une tâche"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{BACKEND_URL}/api/chat/chunks/{task_id}?from_id={from_id}")
        return response.json()

async def stream_from_backend(task_id: str, msg: cl.Message, start_from_chunk: int = 0):
    """Stream depuis backend avec support de reconnexion"""
    
    last_chunk_id = start_from_chunk
    start_time = datetime.now()
    
    while True:
        try:
            chunks_data = await get_chunks(task_id, last_chunk_id)
            
            for chunk in chunks_data["chunks"]:
                await msg.stream_token(chunk["text"])
                last_chunk_id = chunk["chunk_id"] + 1
            
            status = await get_task_status(task_id)
            
            if status.get("status") == "completed":
                elapsed = (datetime.now() - start_time).total_seconds()
                
                await msg.stream_token("\n\n---\n\n")
                await msg.stream_token(f"✅ Terminé en {elapsed:.2f}s\n")
                await msg.stream_token(f"📊 Total chunks: {last_chunk_id}\n")
                
                break
            
            if status.get("status") == "error":
                await msg.stream_token(f"\n\n❌ Error: {status.get('error')}")
                break
            
            await asyncio.sleep(0.2)
            
        except Exception as e:
            await msg.stream_token(f"\n\n❌ Erreur: {str(e)}")
            break

# ==================== RECONNEXION AUTOMATIQUE ====================

async def restore_conversation_history(user_id: str) -> bool:
    """
    Restaure TOUTE la conversation précédente (pas juste tâches en cours)
    
    Returns:
        True si conversation restaurée, False sinon
    """
    
    # Récupérer l'historique complet
    history = await get_session_history(user_id, limit=10)
    tasks = history.get("tasks", [])
    
    if not tasks:
        return False  # Pas d'historique
    
    print(f"[DEBUG] Found {len(tasks)} tasks in history")
    
    # Afficher un message de restauration
    await cl.Message(
        content=f"# 🔄 Restauration de la Session\n\n"
                f"📜 Chargement de vos {len(tasks)} derniers messages...\n\n"
    ).send()
    
    # Boucle sur TOUTES les tâches
    for i, task_info in enumerate(tasks):
        task_id = task_info["task_id"]
        prompt = task_info["prompt"]
        status = task_info["status"]
        chunks_count = task_info["chunks_count"]
        provider = task_info.get("provider", "openai")
        model = task_info.get("model", "gpt-4o")
        
        # 1. Créer le message utilisateur
        user_msg = cl.Message(
            author="Vous",
            content=prompt
        )
        await user_msg.send()
        
        # 2. Créer la réponse de l'assistant
        assistant_msg = cl.Message(content="")
        
        provider_name = "OpenAI GPT" if provider == "openai" else "Anthropic Claude"
        await assistant_msg.stream_token(f"🤖 **{provider_name}** - {model}\n\n")
        await assistant_msg.stream_token("---\n\n")
        
        # Charger tous les chunks
        chunks_data = await get_chunks(task_id, 0)
        
        for chunk in chunks_data["chunks"]:
            await assistant_msg.stream_token(chunk["text"])
        
        # Si en cours, continuer le streaming
        if status == "running":
            await assistant_msg.stream_token("\n\n---\n\n")
            await assistant_msg.stream_token("⚡ **Génération en cours... reprise automatique**\n\n")
            
            # Continuer depuis le dernier chunk
            await stream_from_backend(task_id, assistant_msg, chunks_count)
        else:
            await assistant_msg.stream_token("\n\n---\n\n")
            await assistant_msg.stream_token(f"✅ Complété ({chunks_count} chunks)\n")
        
        await assistant_msg.send()
    
    # Message final
    await cl.Message(
        content=f"✅ **Session restaurée !**\n\n"
                f"Vous pouvez continuer votre conversation normalement."
    ).send()
    
    return True

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
    
    # Définir user_id
    user_id = STABLE_USER_ID
    cl.user_session.set("user_id", user_id)
    
    # Restauration complète de conversation
    restored = await restore_conversation_history(user_id)
    
    if not restored:
        # Pas d'historique, afficher message de bienvenue
        await show_welcome_message(health)
    
    # Créer settings
    await create_chat_settings()

async def show_welcome_message(health: dict):
    """Afficher le message de bienvenue"""
    
    welcome_msg = "# 🤖 Chatbot LLM avec Reconnexion Auto\n\n"
    welcome_msg += "## ✨ Fonctionnalités\n\n"
    welcome_msg += "✅ Génération continue même après rafraîchissement (F5 ou ⌘+R)\n"
    welcome_msg += "✅ Reconnexion **automatique** à vos sessions en cours\n"
    welcome_msg += "✅ Reprise exactement où vous étiez\n"
    welcome_msg += "✅ **Historique complet restauré** (jusqu'à 10 messages)\n\n"
    welcome_msg += "---\n\n"
    welcome_msg += "## Backend Status\n\n"
    welcome_msg += f"- OpenAI: {'🟢 Configuré' if health.get('openai_configured') else '🔴 Non configuré'}\n"
    welcome_msg += f"- Anthropic: {'🟢 Configuré' if health.get('anthropic_configured') else '🔴 Non configuré'}\n\n"
    welcome_msg += "💬 Envoyez un message pour démarrer !"
    
    await cl.Message(content=welcome_msg).send()

async def create_chat_settings():
    """Créer les paramètres de chat"""
    
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
    
    cl.user_session.set("provider", "openai")
    cl.user_session.set("model", "gpt-4o")
    cl.user_session.set("temperature", 0.7)

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

@cl.on_message
async def main(message: cl.Message):
    """Traitement du message"""
    
    provider = cl.user_session.get("provider", "openai")
    model = cl.user_session.get("model", "gpt-4o")
    temperature = cl.user_session.get("temperature", 0.7)
    user_id = cl.user_session.get("user_id", STABLE_USER_ID)
    
    msg = cl.Message(content="")
    
    try:
        provider_name = "OpenAI GPT" if provider == "openai" else "Anthropic Claude"
        await msg.stream_token(f"🔄 **{provider_name}** - {model}\n\n")
        
        task_data = await create_task(
            message.content,
            provider,
            model,
            temperature,
            user_id
        )
        
        task_id = task_data["task_id"]
        
        await msg.stream_token(f"🆔 Task ID: `{task_id}`\n")
        await msg.stream_token("💡 *Vous pouvez rafraîchir (F5), la génération continuera*\n\n")
        await msg.stream_token("---\n\n")
        
        await stream_from_backend(task_id, msg, 0)
    
    except Exception as e:
        await msg.stream_token(f"\n\n❌ **Erreur**: {str(e)}")
    
    await msg.send()
    
    msg.metadata = {
        "provider": provider,
        "model": model,
        "temperature": temperature,
        "task_id": task_id,
        "user_id": user_id
    }
    await msg.update()