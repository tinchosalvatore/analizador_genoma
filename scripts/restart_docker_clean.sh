#!/bin/bash
# ============================================
# 🧹 Docker Full Cleanup + Compose Rebuild
# Limpia todo Docker (sin tocar /var/lib/docker)
# Luego hace docker compose down, build, up y logs.
# ============================================

set -e  # Detiene el script si ocurre algún error

echo "===== Deteniendo todos los contenedores ====="
docker stop $(docker ps -aq) 2>/dev/null || true

echo "===== Eliminando todos los contenedores ====="
docker rm -f $(docker ps -aq) 2>/dev/null || true

echo "===== Eliminando todas las imágenes ====="
docker rmi -f $(docker images -aq) 2>/dev/null || true

echo "===== Eliminando todos los volúmenes ====="
docker volume rm $(docker volume ls -q) 2>/dev/null || true

echo "===== Eliminando todas las redes (excepto por defecto) ====="
docker network rm $(docker network ls -q | grep -vE "^(|bridge|host|none)$") 2>/dev/null || true

echo "===== Limpiando caché y datos de build ====="
docker system prune -a --volumes -f

echo "===== Ejecutando docker compose down ====="
docker compose down --remove-orphans 2>/dev/null || true

echo "===== Reconstruyendo e iniciando contenedores ====="
docker compose up -d --build

echo "===== Mostrando logs en tiempo real ====="
docker compose logs -f
