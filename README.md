# Free5GC Autoscaling CI/CD

Projet de déploiement et test du scaling automatique de Free5GC sur Minikube avec KEDA.

## Environnement
- HP EliteBook 830 G6, Ubuntu 22.04, 15.4GB RAM, 8 cores
- Minikube v1.38.1, Kubernetes v1.35.4, CNI=flannel
- Free5GC v3.3.0, UERANSIM v3.2.6, KEDA, Prometheus, Grafana

## Structure
free5gc-cicd/
├── start-free5gc.sh          # Démarrage complet du système
├── start-minikube.sh         # Démarrage Minikube
├── Makefile                  # Orchestration des scénarios
├── scripts/
│   ├── deploy-ues.py         # Déployer/supprimer N UEs dynamiquement
│   ├── traffic-gen.py        # Générer trafic calibré via uesimtun0
│   ├── metrics-collector.py  # Collecter métriques Prometheus → CSV
│   ├── compare-results.py    # Comparer les scénarios
│   ├── provision-ues.py      # Provisionner abonnés dans MongoDB
│   ├── update-smf-upf.py     # Mise à jour IPs UPF dans ConfigMap SMF
│   ├── smf-request-exporter.py # Exporter PDU requests
│   └── upf-watcher.py        # Watcher scale UPF
├── deploy/
│   ├── keda/                 # ScaledObjects SMF et UPF
│   ├── monitoring/           # Exporters, ServiceMonitors, Watchers
│   ├── network/              # Multus CNI configs (N3/N4/N6)
│   ├── ueransim/             # Configs gNB et UE
│   └── values-minikube.yaml  # Helm values Free5GC
├── dashboards/
│   └── free5gc-dashboard.json # Dashboard Grafana
└── results/                  # CSV des scénarios de test                                                                                                                                                                                                                                                                                                                     ## Démarrage rapide
```bash
# 1. Démarrer Minikube
./start-minikube.sh

# 2. Démarrer Free5GC
./start-free5gc.sh

# 3. Port-forward Prometheus et Grafana
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090 &
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80 &

# 4. Lancer les scénarios
make scenario-4ues
make scenario-10ues
make scenario-20ues
make compare
```

## Scénarios de test
| Scénario | UEs | UPF max | SMF max | BW max |
|----------|-----|---------|---------|--------|
| 4 UEs    | 4   | 4       | 1       | ~850 kbps |
| 10 UEs   | 10  | 4       | 2       | ~3 Mbps |
| 20 UEs   | 20  | 4       | 3-5     | ~3 Mbps |

## Scaling KEDA
- **SMF** : threshold=4 sessions PDU → 1 replica par 4 sessions
- **UPF** : threshold=400 kbps throughput + wake-up event-driven
