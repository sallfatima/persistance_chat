"""
Frontend Chainlit pour Solution 3 (MVP)
Se connecte au backend FastAPI pour streaming LLM
"""

import chainlit as cl
import httpx
import asyncio
import os
from typing import Optional

# ==================== CONFIGURATION ====================

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Modèles disponibles
OPENAI_MODELS = {
    "gpt-4o": "GPT-4o (Recommandé)",
    "gpt-4o-mini": "GPT-4o Mini (Économique)",
    "gpt-4-turbo-preview": "GPT-4 Turbo",
    "gpt-3.5-turbo": "GPT-3.5 Turbo"
}

ANTHROPIC_MODELS = {
    "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet (Recommandé)",
    "claude-3-opus-20240229": "Claude 3 Opus",
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

async def create_task(prompt: str, provider: str, model: str, temperature: float) -> dict:
    """Créer une tâche de génération sur le backend"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BACKEND_URL}/api/chat/generate",
            json={
                "prompt": prompt,
                "provider": provider,
                "model": model,
                "temperature": temperature
            },
            timeout=10.0
        )
        return response.json()

async def stream_via_websocket(task_id: str, msg: cl.Message):
    """Stream depuis WebSocket backend"""
    
    # WebSocket URL
    ws_url = BACKEND_URL.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/ws/chat/{task_id}"
    
    async with httpx.AsyncClient() as client:
        # Pour simplifier, on utilise polling au lieu de vrai WebSocket
        # car httpx ne supporte pas WebSocket
        # En production, utilisez websockets library
        
        last_chunk_id = 0
        while True:
            # Récupérer nouveaux chunks
            response = await client.get(
                f"{BACKEND_URL}/api/chat/chunks/{task_id}?from_id={last_chunk_id}",
                timeout=5.0
            )
            data = response.json()
            
            for chunk in data["chunks"]:
                if chunk["is_replay"]:
                    # Chunk existant (bleu)
                    await msg.stream_token(chunk["text"])
                else:
                    # Nouveau chunk (vert)
                    await msg.stream_token(chunk["text"])
                
                last_chunk_id = chunk["chunk_id"] + 1
            
            # Check status
            status_response = await client.get(
                f"{BACKEND_URL}/api/chat/status/{task_id}",
                timeout=5.0
            )
            status = status_response.json()
            
            if status.get("status") == "completed":
                break
            
            if status.get("status") == "error":
                await msg.stream_token(f"\n\n❌ Error: {status.get('error')}")
                break
            
            await asyncio.sleep(0.2)

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
    welcome_msg = "# 🤖 Chatbot LLM avec Backend FastAPI\n\n"
    welcome_msg += "**Backend Status:**\n"
    welcome_msg += f"- OpenAI: {'🟢 Configuré' if health.get('openai_configured') else '🔴 Non configuré'}\n"
    welcome_msg += f"- Anthropic: {'🟢 Configuré' if health.get('anthropic_configured') else '🔴 Non configuré'}\n\n"
    welcome_msg += "**Architecture:**\n"
    welcome_msg += "```\n"
    welcome_msg += "Chainlit (Frontend) → FastAPI (Backend) → GPT/Claude\n"
    welcome_msg += "```\n\n"
    welcome_msg += "💬 Envoyez un message pour démarrer !"
    
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
    
    try:
        # Afficher info provider
        provider_name = "OpenAI GPT" if provider == "openai" else "Anthropic Claude"
        await msg.stream_token(f"🔄 **{provider_name}** - {model}\n\n")
        
        # Créer tâche sur backend
        task_data = await create_task(
            message.content,
            provider,
            model,
            temperature
        )
        
        task_id = task_data["task_id"]
        
        # Info task
        await msg.stream_token(f"📋 Task ID: `{task_id}`\n\n")
        await msg.stream_token("---\n\n")
        
        # Stream depuis backend
        await stream_via_websocket(task_id, msg)
    
    except Exception as e:
        await msg.stream_token(f"\n\n❌ **Erreur**: {str(e)}")
    
    # Envoyer
    await msg.send()
    
    # Metadata
    msg.metadata = {
        "provider": provider,
        "model": model,
        "temperature": temperature
    }
    await msg.update()

# ==================== PROFILS DE CHAT ====================

@cl.set_chat_profiles
async def chat_profile():
    """Définir profils de chat"""
    
    # Check backend
    health = await check_backend_health()
    
    profiles = []
    
    if health.get("openai_configured"):
        profiles.append(
            cl.ChatProfile(
                name="GPT-4o",
                markdown_description="**OpenAI GPT-4o** via Backend FastAPI",
                icon="https://cdn.openai.com/production/system-images/favicon-32x32.png"
            )
        )
    
    if health.get("anthropic_configured"):
        profiles.append(
            cl.ChatProfile(
                name="Claude-3.5-Sonnet",
                markdown_description="**Claude 3.5 Sonnet** via Backend FastAPI",
                icon="https://www.anthropic.com/favicon.ico"
            )
        )
    
    if not profiles:
        profiles.append(
            cl.ChatProfile(
                name="Unconfigured",
                markdown_description="⚠️ Aucun provider configuré sur le backend",
                icon="https://via.placeholder.com/32"
            )
        )
    
    return profiles
