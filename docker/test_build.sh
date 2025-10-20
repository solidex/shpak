#!/bin/bash
# Quick test script to verify Docker build and structure

set -e

echo "🔨 Building Docker image..."
docker build -f docker/Dockerfile -t shpak-k8s:test .

echo ""
echo "✅ Build successful!"
echo ""
echo "📁 Checking structure in container..."
docker run --rm shpak-k8s:test ls -la /opt/app/app/

echo ""
echo "📦 Checking app modules..."
docker run --rm shpak-k8s:test python -c "
import sys
sys.path.insert(0, '/opt/app')
from app.config import env
from app.models import models
print('✅ All imports work!')
print(f'✅ Config module: {env.__file__}')
print(f'✅ Models module: {models.__file__}')
"

echo ""
echo "🎉 All checks passed! Docker image is ready."

