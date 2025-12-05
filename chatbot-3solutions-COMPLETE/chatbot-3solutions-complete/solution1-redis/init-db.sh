#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" <<-EOSQL
    CREATE DATABASE chatbot_db;
    GRANT ALL PRIVILEGES ON DATABASE chatbot_db TO chatbot;
EOSQL



services:
  postgres:
    image: postgres:16-alpine
    container_name: redis-postgres
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-chatbot}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
      POSTGRES_DB: postgres  # Base par défaut
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./init-db.sh:/docker-entrypoint-initdb.d/init-db.sh  # ← AJOUT
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U chatbot -d chatbot_db"]  # ← CHANGÉ
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - chatbot-network