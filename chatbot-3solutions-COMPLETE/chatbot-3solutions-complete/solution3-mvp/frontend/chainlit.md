# 🤖 Chatbot LLM - Solution MVP

## Architecture Backend + Frontend

Cette solution sépare:
- **Backend FastAPI** (Port 8000) - Streaming LLM
- **Frontend Chainlit** (Port 8501) - Interface utilisateur

## Communication

```
Chainlit → HTTP/WebSocket → FastAPI → GPT/Claude
```

## Fonctionnalités

- ✅ Streaming temps réel
- ✅ Multi-provider (GPT + Claude)
- ✅ Persistance fichiers
- ✅ Reconnexion automatique

Envoyez un message pour commencer !
