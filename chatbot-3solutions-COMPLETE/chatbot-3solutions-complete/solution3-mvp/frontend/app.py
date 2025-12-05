"""
Frontend Chainlit avec user_id STABLE et Debug
Version de diagnostic pour tester la reconnexion
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

async def get_active_sessions(user_id: str) -> dict:
    """Récupérer les sessions actives d'un utilisateur"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            url = f"{BACKEND_URL}/api/sessions/{user_id}/active"
            print(f"[DEBUG] Calling: {url}")
            response = await client.get(url)
            data = response.json()
            print(f"[DEBUG] Sessions response: {json.dumps(data, indent=2)}")
            return data
    except Exception as e:
        print(f"[ERROR] Error getting sessions: {e}")
        return {"active_tasks": [], "count": 0}

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
    is_reconnection = start_from_chunk > 0
    
    if is_reconnection:
        await msg.stream_token(f"\n🔄 **Reprise depuis le chunk #{start_from_chunk}**\n\n")
    
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
                
                if is_reconnection:
                    await msg.stream_token(f"🔄 Session reprise avec succès !\n")
                
                break
            
            if status.get("status") == "error":
                await msg.stream_token(f"\n\n❌ Error: {status.get('error')}")
                break
            
            await asyncio.sleep(0.2)
            
        except Exception as e:
            await msg.stream_token(f"\n\n❌ Erreur: {str(e)}")
            break

# ==================== RECONNEXION ====================

async def check_and_reconnect():
    """Vérifier s'il y a des sessions actives"""
    
    # Utiliser user_id STABLE
    user_id = STABLE_USER_ID
    cl.user_session.set("user_id", user_id)
    
    print(f"[DEBUG] Using stable user_id: {user_id}")
    
    sessions = await get_active_sessions(user_id)
    active_tasks = sessions.get("active_tasks", [])
    
    print(f"[DEBUG] Found {len(active_tasks)} active tasks")
    
    if not active_tasks:
        return None
    
    return active_tasks

async def reconnect_to_task(task_info: dict):
    """Reconnexion à une tâche active"""
    
    task_id = task_info["task_id"]
    prompt = task_info["prompt"]
    chunks_count = task_info["chunks_count"]
    
    print(f"[DEBUG] Reconnecting to task {task_id} with {chunks_count} chunks")
    
    reconnect_msg = cl.Message(content="")
    
    await reconnect_msg.stream_token(f"# 🔄 Reconnexion Réussie !\n\n")
    await reconnect_msg.stream_token(f"**Task ID**: `{task_id}`\n\n")
    await reconnect_msg.stream_token(f"**Prompt**: {prompt}...\n\n")
    await reconnect_msg.stream_token(f"**Progression**: {chunks_count} chunks déjà générés\n\n")
    await reconnect_msg.stream_token("---\n\n")
    
    # Replay chunks existants
    print(f"[DEBUG] Fetching chunks from 0 to {chunks_count}")
    chunks_data = await get_chunks(task_id, 0)
    
    print(f"[DEBUG] Got {len(chunks_data.get('chunks', []))} chunks")
    
    for chunk in chunks_data["chunks"]:
        await reconnect_msg.stream_token(chunk["text"])
    
    # Continuer le streaming
    await stream_from_backend(task_id, reconnect_msg, chunks_count)
    
    await reconnect_msg.send()

# ==================== CHAINLIT HANDLERS ====================

@cl.on_chat_start
async def start():
    """Initialisation avec DEBUG et détection de sessions actives"""
    
    # DEBUG MODE
    debug_info = "# 🔍 DEBUG MODE\n\n"
    
    # Vérifier backend
    health = await check_backend_health()
    debug_info += f"**Backend Status**: {health.get('status')}\n\n"
    
    if health.get("status") == "error":
        await cl.Message(
            content=f"❌ **Backend inaccessible**\n\n"
                    f"Erreur: {health.get('error')}\n\n"
                    f"Assurez-vous que le backend tourne sur {BACKEND_URL}"
        ).send()
        return
    
    # Utiliser user_id STABLE
    user_id = STABLE_USER_ID
    cl.user_session.set("user_id", user_id)
    
    debug_info += f"**User ID (STABLE)**: `{user_id}`\n\n"
    debug_info += "---\n\n"
    
    # Afficher debug
    await cl.Message(content=debug_info).send()
    
    # Vérifier sessions actives
    active_tasks = await check_and_reconnect()
    
    if active_tasks:
        # IL Y A DES SESSIONS ACTIVES !
        msg_content = "# 🔄 Sessions Actives Détectées !\n\n"
        msg_content += f"Vous avez **{len(active_tasks)}** génération(s) en cours:\n\n"
        
        for i, task in enumerate(active_tasks, 1):
            msg_content += f"**{i}.** {task['prompt'][:80]}...\n"
            msg_content += f"   • Task ID: `{task['task_id']}`\n"
            msg_content += f"   • Progression: {task['chunks_count']} chunks\n"
            msg_content += f"   • Status: {task['status']}\n\n"
        
        msg_content += "💡 Voulez-vous reprendre la dernière session ?"
        
        actions = [
            cl.Action(
                name="reconnect",
                value=active_tasks[0]["task_id"],
                label="🔄 Reprendre",
                description="Reprendre la session la plus récente"
            ),
            cl.Action(
                name="new_chat",
                value="new",
                label="🆕 Nouveau",
                description="Commencer une nouvelle conversation"
            )
        ]
        
        await cl.Message(
            content=msg_content,
            actions=actions
        ).send()
        
        cl.user_session.set("pending_reconnect", active_tasks)
        
    else:
        # Pas de sessions actives
        await cl.Message(content="ℹ️ Aucune session active trouvée. Commencez une nouvelle conversation !").send()
        await show_welcome_message(health)
    
    await create_chat_settings()

@cl.action_callback("reconnect")
async def on_reconnect(action: cl.Action):
    """Action: Reprendre une session"""
    
    task_id = action.value
    active_tasks = cl.user_session.get("pending_reconnect", [])
    
    print(f"[DEBUG] Reconnect action for task_id: {task_id}")
    
    task_info = next((t for t in active_tasks if t["task_id"] == task_id), None)
    
    if task_info:
        await reconnect_to_task(task_info)
    else:
        await cl.Message(content="❌ Session introuvable").send()

@cl.action_callback("new_chat")
async def on_new_chat(action: cl.Action):
    """Action: Nouveau chat"""
    
    print("[DEBUG] Starting new chat")
    await cl.Message(content="✨ Nouvelle conversation démarrée !").send()
    
    health = await check_backend_health()
    await show_welcome_message(health)

async def show_welcome_message(health: dict):
    """Afficher le message de bienvenue"""
    
    welcome_msg = "# 🤖 Chatbot LLM avec Reconnexion Auto\n\n"
    welcome_msg += "## ✨ Fonctionnalité: Sessions Persistantes\n\n"
    welcome_msg += f"**Votre User ID**: `{STABLE_USER_ID}` *(STABLE)*\n\n"
    welcome_msg += "✅ Votre génération continue même si vous rafraîchissez (⌘+R)\n"
    welcome_msg += "✅ Reconnexion automatique à vos sessions en cours\n"
    welcome_msg += "✅ Reprise exactement où vous étiez\n\n"
    welcome_msg += "---\n\n"
    welcome_msg += "## Backend Status\n\n"
    welcome_msg += f"- OpenAI: {'🟢' if health.get('openai_configured') else '🔴'}\n"
    welcome_msg += f"- Anthropic: {'🟢' if health.get('anthropic_configured') else '🔴'}\n\n"
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
    
    print(f"[DEBUG] Creating task for user_id: {user_id}")
    
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
        
        print(f"[DEBUG] Task created: {task_id}")
        
        await msg.stream_token(f"🆔 Task ID: `{task_id}`\n")
        await msg.stream_token(f"👤 User ID: `{user_id}` *(STABLE)*\n")
        await msg.stream_token("💡 *Cette session sera récupérable après ⌘+R*\n\n")
        await msg.stream_token("---\n\n")
        
        await stream_from_backend(task_id, msg, 0)
    
    except Exception as e:
        print(f"[ERROR] {str(e)}")
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