# app.py - Solution MVP avec Chainlit
import chainlit as cl
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
import os
from pathlib import Path
import json
from datetime import datetime

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# Storage
STORAGE_DIR = Path("/tmp/chainlit_storage")
STORAGE_DIR.mkdir(exist_ok=True)

@cl.on_chat_start
async def start():
    """Démarrage de la conversation"""
    
    # Sélecteur de provider
    settings = await cl.ChatSettings(
        [
            cl.input_widget.Select(
                id="Provider",
                label="LLM Provider",
                values=["OpenAI GPT", "Anthropic Claude"],
                initial_value="OpenAI GPT"
            ),
            cl.input_widget.Select(
                id="Model",
                label="Model",
                values=["gpt-4o", "gpt-4o-mini"],
                initial_value="gpt-4o"
            )
        ]
    ).send()
    
    # Sauvegarder dans session
    cl.user_session.set("provider", "openai")
    cl.user_session.set("model", "gpt-4o")
    
    # Message de bienvenue
    await cl.Message(
        content="🤖 Bonjour ! Je peux streamer du texte avec GPT ou Claude. Envoyez-moi un message !"
    ).send()

@cl.on_settings_update
async def update_settings(settings):
    """Mise à jour des settings"""
    provider = settings["Provider"]
    model = settings["Model"]
    
    # Update session
    if provider == "OpenAI GPT":
        cl.user_session.set("provider", "openai")
        if model not in ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo-preview"]:
            model = "gpt-4o"
    else:
        cl.user_session.set("provider", "anthropic")
        if model not in ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"]:
            model = "claude-3-5-sonnet-20241022"
    
    cl.user_session.set("model", model)
    
    await cl.Message(
        content=f"✅ Configuration mise à jour: {provider} - {model}"
    ).send()

@cl.on_message
async def main(message: cl.Message):
    """Traitement du message avec streaming"""
    
    provider = cl.user_session.get("provider", "openai")
    model = cl.user_session.get("model", "gpt-4o")
    
    # Créer message de réponse
    msg = cl.Message(content="")
    
    # Générer ID unique pour persistance
    task_id = f"{cl.user_session.get('id')}_{datetime.now().timestamp()}"
    
    try:
        if provider == "openai" and openai_client:
            # Streaming OpenAI
            stream = await openai_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": message.content}],
                stream=True
            )
            
            full_response = ""
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_response += token
                    
                    # STREAMING NATIF vers UI !
                    await msg.stream_token(token)
                    
                    # Sauvegarder chunk (persistance)
                    save_chunk(task_id, full_response)
        
        elif provider == "anthropic" and anthropic_client:
            # Streaming Anthropic
            async with anthropic_client.messages.stream(
                model=model,
                max_tokens=4000,
                messages=[{"role": "user", "content": message.content}]
            ) as stream:
                full_response = ""
                async for text in stream.text_stream:
                    full_response += text
                    
                    # STREAMING NATIF vers UI !
                    await msg.stream_token(text)
                    
                    # Sauvegarder chunk
                    save_chunk(task_id, full_response)
        
        else:
            await msg.stream_token("❌ Provider non configuré ou API key manquante")
    
    except Exception as e:
        await msg.stream_token(f"\n\n❌ Erreur: {str(e)}")
    
    # Envoyer message final
    await msg.send()
    
    # Ajouter metadata
    msg.metadata = {
        "provider": provider,
        "model": model,
        "task_id": task_id
    }
    await msg.update()

def save_chunk(task_id: str, content: str):
    """Sauvegarder pour persistance"""
    file_path = STORAGE_DIR / f"{task_id}.json"
    with open(file_path, 'w') as f:
        json.dump({
            "content": content,
            "updated_at": datetime.now().isoformat()
        }, f)

# Configuration Chainlit
@cl.set_chat_profiles
async def chat_profile():
    return [
        cl.ChatProfile(
            name="GPT-4o",
            markdown_description="OpenAI GPT-4o - Rapide et intelligent",
            icon="https://openai.com/favicon.ico"
        ),
        cl.ChatProfile(
            name="Claude",
            markdown_description="Anthropic Claude 3.5 Sonnet",
            icon="https://www.anthropic.com/favicon.ico"
        )
    ]