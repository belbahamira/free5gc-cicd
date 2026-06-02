# Free5GC Autoscaling CI/CD

Projet de déploiement et test du scaling automatique de Free5GC sur Minikube avec KEDA.

## Environnement
- HP EliteBook 830 G6, Ubuntu 22.04, 15.4GB RAM, 8 cores
- Minikube v1.38.1, Kubernetes v1.35.4, CNI=flannel
- Free5GC v3.3.0, UERANSIM v3.2.6, KEDA, Prometheus, Grafana

## Prérequis

### 1. Installer Docker
```bash
sudo apt-get update
sudo apt-get install -y docker.io
sudo usermod -aG docker $USER
newgrp docker
```

### 2. Installer kubectl
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

### 3. Installer Minikube
```bash
curl -LO https://storage.googleapis.com/minikube/releases/v1.38.1/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
```

### 4. Installer Helm
```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

### 5. Installer gtp5g (module kernel 5G)
```bash
sudo apt-get install -y git gcc make linux-headers-$(uname -r)
git clone https://github.com/free5gc/gtp5g.git
cd gtp5g && git checkout v0.8.5
make && sudo make install
cd ..
```

### 6. Installer Multus CNI
```bash
kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset.yml
```

### 7. Installer KEDA
```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda --namespace keda --create-namespace
```

### 8. Installer Prometheus + Grafana (kube-prometheus-stack)
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace
```

### 9. Installer Free5GC via Helm
```bash
helm repo add towards5gs https://raw.githubusercontent.com/towards5gs/5gcharts/main
helm repo update
helm install free5gc towards5gs/free5gc \
  -n free5gc --create-namespace \
  -f deploy/values-minikube.yaml
```

### 10. Appliquer les configs réseau Multus
```bash
kubectl apply -f deploy/network/
```

### 11. Déployer les exporters et watchers
```bash
kubectl apply -f deploy/monitoring/
```

### 12. Appliquer les ScaledObjects KEDA
```bash
kubectl apply -f deploy/keda/
```

### 13. Déployer UERANSIM
```bash
helm install ueransim towards5gs/ueransim \
  -n free5gc \
  -f deploy/ueransim/ueransim-values.yaml
```

### 14. Importer le dashboard Grafana
```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80 &
# Ouvrir http://localhost:3000
# Importer dashboards/free5gc-dashboard.json
```

## Démarrage rapide
```bash
# 1. Démarrer Minikube
./start-minikube.sh

# 2. Démarrer Free5GC
./start-free5gc.sh

# 3. Port-forward Prometheus et Grafana
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090 &
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80 &

# 4. Provisionner les abonnés (à faire une seule fois)
python3 scripts/provision-ues.py --count 50 --start 6

# 5. Lancer les scénarios
make scenario-4ues
make scenario-10ues
make scenario-20ues
make compare
```


## Structure
```text
free5gc-cicd/
├── start-free5gc.sh          # Démarrage complet du système
├── start-minikube.sh         # Démarrage Minikube
├── setup.sh                  # Installation sur nouveau PC
├── Makefile                  # Orchestration des scénarios
├── scripts/
│   ├── deploy-ues.py         # Déployer/supprimer N UEs dynamiquement
│   ├── traffic-gen.py        # Générer trafic calibré via uesimtun0
│   ├── metrics-collector.py  # Collecter métriques Prometheus -> CSV
│   ├── compare-results.py    # Comparer les scénarios
│   ├── provision-ues.py      # Provisionner abonnés dans MongoDB
│   ├── update-smf-upf.py     # Mise à jour IPs UPF dans ConfigMap SMF
│   ├── smf-request-exporter.py
│   └── upf-watcher.py
├── deploy/
│   ├── keda/                 # ScaledObjects SMF et UPF
│   ├── monitoring/           # Exporters, ServiceMonitors, Watchers
│   ├── network/              # Multus CNI configs N3/N4/N6
│   ├── ueransim/             # Configs gNB et UE + ConfigMaps
│   └── values-minikube.yaml  # Helm values Free5GC
├── docker/
│   ├── pdu-exporter/         # Dockerfile + exporter.py
│   ├── smf-request-exporter/ # Dockerfile + smf-request-exporter.py
│   └── upf-sidecar/          # Dockerfile + sidecar.py
├── dashboards/
│   └── free5gc-dashboard.json
└── results/                  # CSV des scénarios
```

## Scaling KEDA
- **SMF** : threshold=4 sessions PDU → 1 replica par 4 sessions
- **UPF** : threshold=400 kbps throughput + wake-up event-driven + CPU 80%
- **UPF minReplicas=1** pendant les tests (pas de scale-to-zero)
- **cooldownPeriod=30s** pour UPF

## Résultats observés
| Scénario | UEs | UPF max | SMF max | BW max    | CPU SMF |
|----------|-----|---------|---------|-----------|---------|
| 4 UEs    | 4   | 4       | 1       | ~850 kbps | ~3mc    |
| 10 UEs   | 10  | 4       | 2       | ~3 Mbps   | ~10mc   |
| 20 UEs   | 20  | 4       | 3-5     | ~3 Mbps   | ~65mc   |
