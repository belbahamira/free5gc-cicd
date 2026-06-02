#!/usr/bin/env python3
"""
metrics-collector.py — Collecter metriques Prometheus -> CSV
Usage:
  python3 metrics-collector.py --duration 120 --interval 5 --output results.csv
  python3 metrics-collector.py --scenario "10ues" --duration 180
"""
import argparse, csv, datetime, json, os, sys, time, urllib.request, urllib.error

PROMETHEUS_URL = "http://localhost:9090"
DEFAULT_OUT    = "metrics.csv"

METRICS = {
    "upf_replicas":   'kube_deployment_spec_replicas{deployment="free5gc-free5gc-upf-upf"}',
    "smf_replicas":   'kube_deployment_spec_replicas{deployment="free5gc-free5gc-smf-smf"}',
    "pdu_sessions":   "free5gc_pdu_sessions_total",
    "pdu_requests":   "increase(free5gc_pdu_session_requests_total[30s])",
    "upf_throughput": "sum(free5gc_upf_throughput_bps)",
    "cpu_smf_mc":     "sum(rate(container_cpu_usage_seconds_total{pod=~\"free5gc-free5gc-smf.*\",cpu=\"total\"}[1m]))*1000",
    "cpu_upf_mc":     "sum(rate(container_cpu_usage_seconds_total{pod=~\"free5gc-free5gc-upf.*\",cpu=\"total\"}[1m]))*1000",
}

def query(expr):
    url = f"{PROMETHEUS_URL}/api/v1/query?query={urllib.request.quote(expr)}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        results = data.get("data",{}).get("result",[])
        if results:
            return float(results[0]["value"][1])
        return None
    except Exception:
        return None

def collect_row(scenario, ts):
    row = {"timestamp": ts, "scenario": scenario}
    for key, expr in METRICS.items():
        val = query(expr)
        row[key] = round(val, 3) if val is not None else ""
    return row

def print_row(row):
    print(f"  [{row['timestamp']}] "
          f"UPF={row.get('upf_replicas','-')} "
          f"SMF={row.get('smf_replicas','-')} "
          f"PDU={row.get('pdu_sessions','-')} "
          f"BW={row.get('upf_throughput','-')}bps "
          f"CPU_SMF={row.get('cpu_smf_mc','-')}mc "
          f"CPU_UPF={row.get('cpu_upf_mc','-')}mc")

def check_prometheus():
    try:
        with urllib.request.urlopen(f"{PROMETHEUS_URL}/-/healthy", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False

def main():
    p = argparse.ArgumentParser(description="Collecteur metriques Prometheus -> CSV")
    p.add_argument("--duration", type=int,   default=120,
                   help="Duree de collecte en secondes (defaut: 120)")
    p.add_argument("--interval", type=int,   default=5,
                   help="Intervalle entre mesures en secondes (defaut: 5)")
    p.add_argument("--output",   default=DEFAULT_OUT,
                   help="Fichier CSV de sortie (defaut: metrics.csv)")
    p.add_argument("--scenario", default="default",
                   help="Nom du scenario (defaut: default)")
    global PROMETHEUS_URL
    p.add_argument("--prometheus", default=PROMETHEUS_URL,
                   help=f"URL Prometheus (defaut: {PROMETHEUS_URL})")
    p.add_argument("--append",   action="store_true",
                   help="Ajouter au CSV existant au lieu d\x27ecraser")
    args = p.parse_args()

    PROMETHEUS_URL = args.prometheus

    if not check_prometheus():
        print(f"[ERREUR] Prometheus inaccessible a {PROMETHEUS_URL}")
        print("  -> Verifiez: kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090 &")
        sys.exit(1)
    print(f"[OK] Prometheus accessible: {PROMETHEUS_URL}")

    fieldnames = ["timestamp","scenario"] + list(METRICS.keys())
    mode = "a" if args.append else "w"
    write_header = not args.append or not os.path.exists(args.output)

    print(f"[INFO] Scenario={args.scenario} | Duree={args.duration}s | "
          f"Intervalle={args.interval}s | Sortie={args.output}")
    print(f"[INFO] Debut collecte...\n")

    samples = 0
    start   = time.time()
    deadline = start + args.duration

    with open(args.output, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()

        while time.time() < deadline:
            ts  = datetime.datetime.now().strftime("%H:%M:%S")
            row = collect_row(args.scenario, ts)
            writer.writerow(row)
            f.flush()
            print_row(row)
            samples += 1
            remaining = deadline - time.time()
            if remaining > 0:
                time.sleep(min(args.interval, remaining))

    elapsed = round(time.time() - start, 1)
    print(f"\n[FIN] {samples} mesures en {elapsed}s -> {args.output}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[STOP] Collecte interrompue (Ctrl+C)")
        sys.exit(0)
