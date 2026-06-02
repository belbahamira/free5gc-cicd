#!/bin/bash
echo "🚀 Démarrage de Minikube..."
minikube start \
  --driver=docker \
  --cpus=6 \
  --memory=12288 \
  --disk-size=40g \
  --kubernetes-version=v1.35.4 \
  --cni=flannel

echo "✅ Minikube est prêt !"
minikube status
