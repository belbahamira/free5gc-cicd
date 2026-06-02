from prometheus_client import start_http_server, Gauge
import requests, time, re

pdu_sessions = Gauge("free5gc_pdu_sessions_total", "Active PDU sessions")

def count_pdu_sessions():
    try:
        with open("/var/run/secrets/kubernetes.io/serviceaccount/token") as f:
            token = f.read()
        with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace") as f:
            namespace = f.read().strip()
        headers = {"Authorization": "Bearer " + token}
        ca = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

        # Récupérer les pods SMF
        url = f"https://kubernetes.default.svc/api/v1/namespaces/{namespace}/pods?labelSelector=nf=smf"
        pods = requests.get(url, headers=headers, verify=ca).json().get("items", [])

        total = 0
        for pod in pods:
            pod_name = pod["metadata"]["name"]
            if pod.get("status", {}).get("phase") != "Running":
                continue

            # Lire seulement les dernières 300 secondes de logs
            log_url = (f"https://kubernetes.default.svc/api/v1/namespaces/{namespace}"
                      f"/pods/{pod_name}/log?container=smf&sinceSeconds=300")
            logs = requests.get(log_url, headers=headers, verify=ca).text

            established = logs.count("PFCP Session Establishment Accepted Response")
            released = logs.count("PFCP Session Deletion Response")
            active = max(0, established - released)
            print(f"Pod {pod_name}: {active} active (est={established} rel={released})", flush=True)
            total += active

        return total
    except Exception as e:
        print(f"Error: {e}", flush=True)
        return 0

start_http_server(8080)
print("Exporter started (fixed)", flush=True)
while True:
    count = count_pdu_sessions()
    pdu_sessions.set(count)
    print(f"PDU sessions active total: {count}", flush=True)
    time.sleep(15)
