# ⚡ Chatbot LLM - Temporal Workflows

## Architecture Enterprise

```
Chainlit → FastAPI → Temporal Server → Workers → GPT/Claude
                                         ↓
                                    Temporal UI
```

## ⚡ Crash Recovery

**Le workflow reprend EXACTEMENT où il était après un crash !**

### Test:
1. Lancez génération longue
2. `docker-compose stop worker` (pendant génération)
3. Attendez 30s
4. `docker-compose start worker`
5. ✅ Reprend au dernier checkpoint !

## 📊 Monitoring

**Temporal UI**: http://localhost:8080

Voir tous les workflows:
- État en temps réel
- Historique complet
- Logs détaillés
- Retry automatiques

## 🎯 Avantages

- ✅ Checkpointing automatique
- ✅ Reprise auto sur crash
- ✅ Event sourcing complet
- ✅ Observabilité totale

Envoyez un message pour démarrer un workflow !
