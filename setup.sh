#!/bin/bash
# setup.sh — Installation complète Free5GC autoscaling sur nouveau PC
set -e
echo "=== Setup Free5GC Autoscaling ==="

# 1. Build images Docker custom
echo "[1/4] Build images Docker..."
cd docker/pdu-exporter
docker build -t pdu-exporter:latest .
cd ../smf-request-exporter
docker build -t smf-request-exporter:latest .
cd ../upf-sidecar
docker build -t upf-sidecar:latest .
cd ../..

# Charger les images dans Minikube
echo "[2/4] Chargement images dans Minikube..."
minikube image load pdu-exporter:latest
minikube image load smf-request-exporter:latest
minikube image load upf-sidecar:latest

# 3. Appliquer les configs réseau
echo "[3/4] Application configs réseau..."
kubectl apply -f deploy/network/

# 4. Déployer monitoring + KEDA
echo "[4/4] Déploiement monitoring et KEDA..."
kubectl apply -f deploy/monitoring/
kubectl apply -f deploy/keda/

# 5. Appliquer ConfigMaps UE
echo "[5/5] ConfigMaps UE..."
kubectl apply -f deploy/ueransim/configmaps/
kubectl apply -f deploy/ueransim/gnb-configmap.yaml

# 6. Provisionner abonnés MongoDB
echo "[6/6] Provisioning abonnés MongoDB (006-055)..."
python3 scripts/provision-ues.py --count 50 --start 6

echo "=== Setup terminé ==="
echo "Lance: ./start-free5gc.sh"
