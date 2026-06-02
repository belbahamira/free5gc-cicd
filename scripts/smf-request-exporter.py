from prometheus_client import start_http_server, Counter, Gauge
import requests, time, threading

# Métriques
pdu_requests = Counter(
    'free5gc_pdu_session_requests_total',
    'Total PDU session establishment requests received by SMF'
)
pdu_sessions = Gauge(
    'free5gc_pdu_sessions_active',
    'Active PDU sessions in SMF'
)

def get_k8s_headers():
    with open("/var/run/secrets/kubernetes.io/serviceaccount/token") as f:
        token = f.read()
    with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace") as f:
        namespace = f.read().strip()
    ca = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    return {"Authorization": "Bearer " + token}, ca, namespace

def get_smf_pods(headers, ca, namespace):
    url = f"https://kubernetes.default.svc/api/v1/namespaces/{namespace}/pods?labelSelector=nf=smf"
    r = requests.get(url, headers=headers, verify=ca)
    return [p["metadata"]["name"] for p in r.json().get("items", [])
            if p.get("status", {}).get("phase") == "Running"]

def stream_smf_logs(pod_name, namespace, headers, ca):
    """Stream les logs SMF depuis sinceSeconds=0"""
    seen_lines = set()
    since = 60  # dernières 60s au démarrage
    
    while True:
        try:
            url = (f"https://kubernetes.default.svc/api/v1/namespaces/{namespace}"
                   f"/pods/{pod_name}/log?container=smf&sinceSeconds={since}&follow=false")
            r = requests.get(url, headers=headers, verify=ca, timeout=30)
            
            active = 0
            for line in r.text.strip().split("\n"):
                if not line or line in seen_lines:
                    continue
                seen_lines.add(line)
                
                # Détecter requêtes PDU entrantes
                if "HandlePDUSessionEstablishmentRequest" in line:
                    pdu_requests.inc()
                    print(f"[SMF-EXPORTER] PDU request detected: +1", flush=True)
                
                # Compter sessions actives
                if "Allocated PDUAdress" in line:
                    active += 1
                if "Release IP" in line or "smContext" in line and "deleted" in line:
                    active -= 1
            
            # Garder seulement les 300 dernières secondes
            since = 300
            time.sleep(5)
            
        except Exception as e:
            print(f"[SMF-EXPORTER] Error streaming {pod_name}: {e}", flush=True)
            time.sleep(10)

def watch_smf_pods():
    """Surveille les pods SMF et lance un thread par pod"""
    headers, ca, namespace = get_k8s_headers()
    active_threads = {}
    
    while True:
        try:
            pods = get_smf_pods(headers, ca, namespace)
            
            for pod in pods:
                if pod not in active_threads or not active_threads[pod].is_alive():
                    print(f"[SMF-EXPORTER] Starting log stream for {pod}", flush=True)
                    t = threading.Thread(
                        target=stream_smf_logs,
                        args=(pod, namespace, headers, ca),
                        daemon=True
                    )
                    t.start()
                    active_threads[pod] = t
            
            time.sleep(15)
            
        except Exception as e:
            print(f"[SMF-EXPORTER] Watch error: {e}", flush=True)
            time.sleep(10)

print("[SMF-EXPORTER] Starting on port 8001...", flush=True)
start_http_server(8001)
watch_smf_pods()
