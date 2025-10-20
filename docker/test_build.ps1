# Quick test script to verify Docker build and structure (PowerShell version)

Write-Host "🔨 Building Docker image..." -ForegroundColor Cyan
docker build -f docker/Dockerfile -t shpak-k8s:test .

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ Build successful!" -ForegroundColor Green
    Write-Host ""
    
    Write-Host "📁 Checking structure in container..." -ForegroundColor Cyan
    docker run --rm shpak-k8s:test ls -la /opt/app/app/
    
    Write-Host ""
    Write-Host "📦 Checking app modules..." -ForegroundColor Cyan
    docker run --rm shpak-k8s:test python -c @"
import sys
sys.path.insert(0, '/opt/app')
from app.config import env
from app.models import models
print('✅ All imports work!')
print(f'✅ Config module: {env.__file__}')
print(f'✅ Models module: {models.__file__}')
"@
    
    Write-Host ""
    Write-Host "🎉 All checks passed! Docker image is ready." -ForegroundColor Green
} else {
    Write-Host "❌ Build failed!" -ForegroundColor Red
    exit 1
}

