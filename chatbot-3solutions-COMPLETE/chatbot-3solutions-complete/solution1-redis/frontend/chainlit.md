# 🚀 Chatbot LLM - Redis + PostgreSQL

## Architecture Production

```
Chainlit → FastAPI → Redis (Cache) + PostgreSQL (Data) → GPT/Claude
```

## Cache Redis

- **TTL**: 1 heure
- **Avantage**: Réponses instantanées pour prompts identiques
- **Économie**: Moins d'appels LLM = moins de coûts

## Test Cache

1. Envoyez un message : "Explique-moi l'IA"
2. Attendez la réponse complète (~5-10s)
3. Envoyez **exactement le même message**
4. ⚡ Réponse instantanée depuis le cache !

## Persistance PostgreSQL

Toutes les générations sont sauvegardées en base de données.

Envoyez un message pour commencer !
