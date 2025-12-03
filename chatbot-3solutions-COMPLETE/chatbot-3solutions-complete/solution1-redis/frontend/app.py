"""
Frontend Chainlit pour Solution 1 (Redis + PostgreSQL)
Affiche si réponse vient du cache ou non
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

async def get_backend_stats() -> dict:
    """Récupérer statistiques backend"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BACKEND_URL}/api/stats", timeout=5.0)
            return response.json()
    except Exception as e:
        return {}

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

async def stream_from_backend(task_id: str, msg: cl.Message, cached: bool):
    """Stream depuis backend avec polling"""
    
    # Si cached, afficher badge immédiatement
    if cached:
        await msg.stream_token("🎯 **CACHE HIT** - Réponse instantanée depuis Redis !\n\n")
        await msg.stream_token("---\n\n")
    
    last_chunk_id = 0
    start_time = datetime.now()
    
    while True:
        # Récupérer nouveaux chunks
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BACKEND_URL}/api/chat/chunks/{task_id}?from_id={last_chunk_id}",
                timeout=5.0
            )
            data = response.json()
        
        # Afficher chunks
        for chunk in data["chunks"]:
            await msg.stream_token(chunk["text"])
            last_chunk_id = chunk["chunk_id"] + 1
        
        # Check status
        async with httpx.AsyncClient() as client:
            status_response = await client.get(
                f"{BACKEND_URL}/api/chat/status/{task_id}",
                timeout=5.0
            )
            status = status_response.json()
        
        if status.get("status") == "completed":
            # Calculer temps
            elapsed = (datetime.now() - start_time).total_seconds()
            
            # Afficher footer
            await msg.stream_token("\n\n---\n\n")
            await msg.stream_token(f"⏱️ Temps: {elapsed:.2f}s | ")
            await msg.stream_token(f"Provider: {status['provider']} | ")
            await msg.stream_token(f"Model: {status['model']}\n")
            
            if cached:
                await msg.stream_token("💾 Réponse servie depuis le cache Redis (TTL: 1h)\n")
            else:
                await msg.stream_token("🆕 Nouvelle génération - Maintenant en cache pour 1h\n")
            
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
    
    # Récupérer stats
    stats = await get_backend_stats()
    
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
    welcome_msg = "# 🚀 Chatbot LLM - Redis + PostgreSQL\n\n"
    welcome_msg += "## Architecture\n\n"
    welcome_msg += "```\n"
    welcome_msg += "Chainlit → FastAPI → Redis (cache) + PostgreSQL (data) → GPT/Claude\n"
    welcome_msg += "```\n\n"
    
    welcome_msg += "## Backend Status\n\n"
    welcome_msg += f"- OpenAI: {'🟢 Configuré' if health.get('openai_configured') else '🔴 Non configuré'}\n"
    welcome_msg += f"- Anthropic: {'🟢 Configuré' if health.get('anthropic_configured') else '🔴 Non configuré'}\n"
    welcome_msg += f"- Redis: {'🟢 Connecté' if health.get('redis_connected') else '🔴 Déconnecté'}\n"
    welcome_msg += f"- PostgreSQL: {'🟢 Connecté' if health.get('postgres_connected') else '🔴 Déconnecté'}\n\n"
    
    if stats:
        welcome_msg += "## Statistiques Cache\n\n"
        welcome_msg += f"- Total générations: {stats.get('total_tasks', 0)}\n"
        welcome_msg += f"- Depuis cache: {stats.get('cached_tasks', 0)}\n"
        welcome_msg += f"- Taux de hit: {stats.get('cache_hit_rate', '0%')}\n"
        welcome_msg += f"- Total chunks: {stats.get('total_chunks', 0)}\n\n"
    
    welcome_msg += "## Comment ça marche ?\n\n"
    welcome_msg += "1. **Première génération** : Le backend appelle GPT/Claude et sauvegarde dans Redis (TTL 1h)\n"
    welcome_msg += "2. **Générations suivantes** : Si même prompt dans l'heure, réponse instantanée depuis Redis !\n"
    welcome_msg += "3. **Persistance** : Toutes les générations sont sauvegardées dans PostgreSQL\n\n"
    welcome_msg += "💡 **Astuce**: Envoyez le même message 2x pour voir la différence de vitesse !\n\n"
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
        await msg.stream_token(f"🔄 **{provider_name}** - {model}\n")
        await msg.stream_token(f"📋 Température: {temperature}\n\n")
        await msg.stream_token("⏳ Création de la tâche...\n\n")
        
        # Créer tâche sur backend
        task_data = await create_task(
            message.content,
            provider,
            model,
            temperature
        )
        
        task_id = task_data["task_id"]
        cached = task_data.get("cached", False)
        
        # Effacer "Création de la tâche..."
        msg.content = f"🔄 **{provider_name}** - {model}\n"
        msg.content += f"📋 Température: {temperature}\n"
        msg.content += f"🆔 Task ID: `{task_id}`\n\n"
        msg.content += "---\n\n"
        await msg.update()
        
        # Stream depuis backend
        await stream_from_backend(task_id, msg, cached)
    
    except Exception as e:
        await msg.stream_token(f"\n\n❌ **Erreur**: {str(e)}")
    
    # Envoyer
    await msg.send()
    
    # Metadata
    msg.metadata = {
        "provider": provider,
        "model": model,
        "temperature": temperature,
        "task_id": task_id,
        "cached": cached
    }
    await msg.update()

@cl.action_callback("refresh_stats")
async def refresh_stats(action):
    """Rafraîchir statistiques"""
    
    stats = await get_backend_stats()
    
    if stats:
        stats_msg = "## 📊 Statistiques Mises à Jour\n\n"
        stats_msg += f"- Total générations: {stats.get('total_tasks', 0)}\n"
        stats_msg += f"- Depuis cache: {stats.get('cached_tasks', 0)}\n"
        stats_msg += f"- Taux de hit: {stats.get('cache_hit_rate', '0%')}\n"
        stats_msg += f"- Total chunks: {stats.get('total_chunks', 0)}\n"
        
        await cl.Message(content=stats_msg).send()
    else:
        await cl.Message(content="❌ Impossible de récupérer les statistiques").send()

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
                name="GPT-4o-Cached",
                markdown_description="**OpenAI GPT-4o** avec cache Redis ultra-rapide",
                icon="https://cdn.openai.com/production/system-images/favicon-32x32.png"
            )
        )
    
    if health.get("anthropic_configured"):
        profiles.append(
            cl.ChatProfile(
                name="Claude-Cached",
                markdown_description="**Claude 3.5 Sonnet** avec cache Redis ultra-rapide",
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
