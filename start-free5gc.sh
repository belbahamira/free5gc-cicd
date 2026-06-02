#!/bin/bash
set -e
echo "=== Démarrage Free5GC ==="

# Vérifier composants permanents
echo "Vérification composants permanents..."
for comp in upf-watcher smf-request-exporter; do
  STATUS=$(kubectl get pod -n free5gc -l app=$comp     -o jsonpath="{.items[0].status.phase}" 2>/dev/null)
  if [ "$STATUS" != "Running" ]; then
    echo "⚠️  $comp non Running (status=$STATUS) — relancement..."
    kubectl rollout restart deployment $comp -n free5gc 2>/dev/null || true
  else
    echo "✅ $comp Running"
  fi
done

# 0. Reset replicas résiduels + pauser KEDA
echo "Nettoyage UEs residuels..."
python3 ~/free5gc-cicd/scripts/deploy-ues.py --delete --start 6 --count 50 2>/dev/null || true
echo "Reset replicas et pause KEDA..."
kubectl scale deployment free5gc-free5gc-smf-smf -n free5gc --replicas=1
kubectl scale deployment free5gc-free5gc-upf-upf -n free5gc --replicas=1
kubectl scale deployment pdu-session-exporter -n free5gc --replicas=1
kubectl scale deployment ueransim-ue-002 ueransim-ue-003 \
  ueransim-ue-004 ueransim-ue-005 -n free5gc --replicas=1
kubectl annotate scaledobject smf-scaler -n free5gc \
  autoscaling.keda.sh/paused-replicas="1" --overwrite
kubectl annotate scaledobject upf-scaler -n free5gc \
  autoscaling.keda.sh/paused-replicas="1" --overwrite
sleep 5

# Pauser le watcher pour éviter les re-syncs pendant le démarrage
echo "Pause watcher..."
kubectl scale deployment upf-watcher -n free5gc --replicas=0
kubectl wait --for=delete pod -l app=upf-watcher -n free5gc --timeout=30s 2>/dev/null || true

# 1. Reset pool host-local UPF + SMF
kubectl scale deployment free5gc-free5gc-upf-upf -n free5gc --replicas=0
echo "Attente arrêt complet UPF..."
for i in $(seq 1 30); do
  PODS=$(kubectl get pods -n free5gc -l nf=upf --no-headers 2>/dev/null)
  if [ -z "$PODS" ]; then
    echo "✅ UPF arrêté"
    break
  fi
  echo "  Attente arrêt UPF... ($i/30)"
  sleep 3
done
sleep 3
minikube ssh "sudo find /var/lib/cni/networks/n4network-free5gc-free5gc-upf/ -type f ! -name 'last_reserved_ip.0' ! -name 'lock' -delete 2>/dev/null || true"
minikube ssh "sudo bash -c 'echo -n 10.100.51.0 > /var/lib/cni/networks/n4network-free5gc-free5gc-upf/last_reserved_ip.0'"
minikube ssh "sudo find /var/lib/cni/networks/n3network-free5gc-free5gc-upf/ -type f ! -name 'last_reserved_ip.0' ! -name 'lock' -delete 2>/dev/null || true"
minikube ssh "sudo bash -c 'echo -n 10.100.51.32 > /var/lib/cni/networks/n3network-free5gc-free5gc-upf/last_reserved_ip.0'"
minikube ssh "sudo find /var/lib/cni/networks/n6network-free5gc-free5gc-upf/ -type f ! -name 'last_reserved_ip.0' ! -name 'lock' -delete 2>/dev/null || true"
minikube ssh "sudo bash -c 'echo -n 10.100.100.11 > /var/lib/cni/networks/n6network-free5gc-free5gc-upf/last_reserved_ip.0'"
minikube ssh "sudo find /var/lib/cni/networks/n4network-free5gc-free5gc-smf/ -type f ! -name 'last_reserved_ip.0' ! -name 'lock' -delete 2>/dev/null || true"
minikube ssh "sudo bash -c 'echo -n 10.100.51.4 > /var/lib/cni/networks/n4network-free5gc-free5gc-smf/last_reserved_ip.0'"

# 2. Démarrer UPF
kubectl scale deployment free5gc-free5gc-upf-upf -n free5gc --replicas=1
echo "Attente UPF Running..."
kubectl wait --for=condition=ready pod -l nf=upf -n free5gc --timeout=90s

# 3. Attendre les annotations réseau UPF (N4 + N3)
echo "Attente annotations réseau UPF..."
UPF_READY=0
for i in $(seq 1 30); do
  N4_IP=$(kubectl get pod -n free5gc -l nf=upf -o json 2>/dev/null | python3 -c "
import json,sys
try:
    pods = json.load(sys.stdin)['items']
    for p in pods:
        if p.get('status',{}).get('phase') != 'Running': continue
        nets = json.loads(p['metadata']['annotations'].get('k8s.v1.cni.cncf.io/network-status','[]'))
        for n in nets:
            if 'n4' in n['name'] and n.get('ips'):
                print(n['ips'][0]); raise SystemExit
except: pass
" 2>/dev/null)
  N3_IP=$(kubectl get pod -n free5gc -l nf=upf -o json 2>/dev/null | python3 -c "
import json,sys
try:
    pods = json.load(sys.stdin)['items']
    for p in pods:
        if p.get('status',{}).get('phase') != 'Running': continue
        nets = json.loads(p['metadata']['annotations'].get('k8s.v1.cni.cncf.io/network-status','[]'))
        for n in nets:
            if 'n3' in n['name'] and n.get('ips'):
                print(n['ips'][0]); raise SystemExit
except: pass
" 2>/dev/null)
  if [ -n "$N4_IP" ] && [ "$N4_IP" != "None" ] && \
     [ -n "$N3_IP" ] && [ "$N3_IP" != "None" ]; then
    echo "✅ IPs UPF disponibles — N4=$N4_IP N3=$N3_IP"
    UPF_READY=1
    break
  fi
  echo "  Attente annotations UPF... ($i/30)"
  sleep 5
done

if [ "$UPF_READY" -eq 0 ]; then
  echo "❌ Timeout : UPF n'a pas ses annotations après 150s."
  kubectl get pods -n free5gc -l nf=upf
  exit 1
fi

# 4. Mettre à jour smfcfg avec IPs UPF
echo "Mise à jour smfcfg..."
python3 ~/update-smf-upf.py

# Fonction restart SMF et attente PFCP
restart_smf_wait_pfcp() {
  kubectl rollout restart deployment free5gc-free5gc-smf-smf -n free5gc
  kubectl wait --for=condition=ready pod -l nf=smf -n free5gc --timeout=120s
  SMF_POD=$(kubectl get pod -n free5gc -l nf=smf -o jsonpath='{.items[0].metadata.name}')
  echo "  Pod SMF: $SMF_POD"
  # Attendre PFCP avec ce pod spécifique
  for j in $(seq 1 20); do
    PFCP=$(kubectl logs -n free5gc $SMF_POD -c smf --since=5m 2>/dev/null | \
      grep "PFCP Association Setup Accepted" | tail -1)
    if [ -n "$PFCP" ]; then
      echo "✅ PFCP établi : $PFCP"
      return 0
    fi
    echo "    Attente PFCP pod $SMF_POD... ($j/20)"
    sleep 3
  done
  return 1
}

# 5. Démarrage SMF
echo "Redémarrage SMF avec config finale..."
if ! restart_smf_wait_pfcp; then
  echo "  Re-sync IPs UPF + 2ème tentative SMF..."
  python3 ~/update-smf-upf.py
  if ! restart_smf_wait_pfcp; then
    echo "❌ Timeout PFCP après 2 tentatives"
    exit 1
  fi
fi

# 6. Règles iptables MASQUERADE
echo "Configuration iptables..."
minikube ssh "sudo iptables -t nat -F POSTROUTING" 2>/dev/null
minikube ssh "sudo iptables -t nat -A POSTROUTING -s 172.17.0.0/16 -j MASQUERADE" 2>/dev/null
minikube ssh "sudo iptables -t nat -A POSTROUTING -s 10.1.0.0/16 ! -d 10.0.0.0/8 -j MASQUERADE" 2>/dev/null

# 7. Redémarrer AMF
echo "Redémarrage AMF..."
kubectl rollout restart deployment free5gc-free5gc-amf-amf -n free5gc
kubectl wait --for=condition=ready pod -l nf=amf -n free5gc --timeout=60s
sleep 30

# 8. Redémarrer gNB
echo "Redémarrage gNB..."
kubectl rollout restart deployment ueransim-gnb -n free5gc
kubectl wait --for=condition=ready pod -l app=ueransim,component=gnb -n free5gc --timeout=60s
sleep 30

# 9. Redémarrer UEs
echo "Redémarrage UEs..."
kubectl rollout restart deployment ueransim-ue-002 ueransim-ue-003 \
  ueransim-ue-004 ueransim-ue-005 -n free5gc
sleep 10

# 10. Attendre tunnels UE
echo "Attente tunnels UE (uesimtun0)..."
for i in $(seq 1 30); do
  ALL_UP=1
  for ue in 002 003 004 005; do
    POD=$(kubectl get pod -n free5gc -l app=ueransim-ue-$ue \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -z "$POD" ]; then ALL_UP=0; break; fi
    if ! kubectl exec -n free5gc $POD -- \
      ip addr show uesimtun0 2>/dev/null | grep -q "inet "; then
      ALL_UP=0; break
    fi
  done
  if [ "$ALL_UP" -eq 1 ]; then
    echo "✅ Tunnels UE disponibles"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "⚠️  Certains tunnels manquants après 300s"
  fi
  echo "  Attente tunnels... ($i/30)"
  sleep 10
done

# 11. Vérifier sessions PDU
echo "=== Vérification PDU ==="
for ue in 002 003 004 005; do
  POD=$(kubectl get pod -n free5gc -l app=ueransim-ue-$ue \
    -o jsonpath='{.items[0].metadata.name}')
  TUNNEL=$(kubectl exec -n free5gc $POD -- \
    ip addr show uesimtun0 2>/dev/null | grep "inet " || echo "NO TUNNEL")
  echo "UE-$ue: $TUNNEL"
done

# 12. Test ping
set +e  # Ne pas quitter sur erreur ping
echo "=== Test ping ==="
PING_OK=0
for ue in 003 004 005 002; do
  UE_POD=$(kubectl get pod -n free5gc -l app=ueransim-ue-$ue \
    -o jsonpath='{.items[0].metadata.name}')
  if kubectl exec -n free5gc $UE_POD -- \
    ip addr show uesimtun0 2>/dev/null | grep -q "inet "; then
    echo "Ping via UE-$ue..."
    kubectl exec -n free5gc $UE_POD -- sh -c "ip route add 8.8.8.8/32 dev uesimtun0 2>/dev/null || true && ping 8.8.8.8 -c 3" || true
    PING_OK=1
    break
  fi
done
if [ "$PING_OK" -eq 0 ]; then
  echo "⚠️  Aucun tunnel disponible pour le ping"
set -e  # Reprendre comportement strict
fi

# 13. Dépauser KEDA
echo "Activation KEDA scalers..."
kubectl annotate scaledobject smf-scaler -n free5gc \
  autoscaling.keda.sh/paused-replicas- --overwrite
kubectl annotate scaledobject upf-scaler -n free5gc \
  autoscaling.keda.sh/paused-replicas- --overwrite

# Reprendre le watcher
echo "Reprise watcher..."
kubectl scale deployment upf-watcher -n free5gc --replicas=1
kubectl wait --for=condition=ready pod -l app=upf-watcher -n free5gc --timeout=60s

echo "=== Free5GC prêt ==="
