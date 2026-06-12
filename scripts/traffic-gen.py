#!/usr/bin/env python3
"""
traffic-gen.py — Générer du trafic calibré via uesimtunX
Usage:
  python3 traffic-gen.py --ues 4 --duration 60 --pps 200 --size 1400
  python3 traffic-gen.py --ues 10 --duration 120 --pps 500
  python3 traffic-gen.py --stop
"""
import subprocess, sys, argparse, time, signal, os, json
from concurrent.futures import ThreadPoolExecutor, as_completed

NAMESPACE  = "free5gc"
TARGET_IP  = "8.8.8.8"
UE_START   = 2          # UE-002 est le premier
LABEL_BASE = "ueransim-ue"

def kubectl(*args, check=False):
    r = subprocess.run(["kubectl"]+list(args), capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"[ERREUR] {r.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return r

def get_ue_pods(count):
    """Retourne la liste des pods UE actifs (jusqu\x27a count)."""
    r = kubectl("get","pods","-n",NAMESPACE,"-o","json")
    pods = json.loads(r.stdout).get("items",[])
    ue_pods = []
    for p in pods:
        name = p["metadata"]["name"]
        phase = p["status"].get("phase","")
        if "ueransim-ue-" in name and phase == "Running":
            ue_pods.append(name)
    ue_pods.sort()
    return ue_pods[:count]

def setup_route(pod):
    """Attend uesimtun0 puis ajoute route."""
    import time as t
    for _ in range(24):  # max 120s
        r = kubectl("exec","-n",NAMESPACE,pod,"--",
                    "ip","addr","show","uesimtun0", check=False)
        if r.returncode == 0:
            break
        t.sleep(5)
    kubectl("exec","-n",NAMESPACE,pod,"--",
            "ip","route","add",f"{TARGET_IP}/32","dev","uesimtun0",
            check=False)

def run_ping(pod, duration, pps, size):
    """Lance ping dans le pod et retourne les stats."""
    interval = round(1.0 / pps, 4)
    count    = int(duration * pps)
    setup_route(pod)
    start = time.time()
    cmd = (f"ip route add {TARGET_IP}/32 dev uesimtun0 2>/dev/null || true && "
           f"ping -I uesimtun0 {TARGET_IP} -c {count} -s {size} -i {interval} -W 2")
    r = kubectl("exec","-n",NAMESPACE,pod,"--","sh","-c",cmd)
    elapsed = time.time() - start
    return parse_ping(pod, r.stdout, elapsed)

def parse_ping(pod, output, elapsed):
    """Parse la sortie ping → dict stats."""
    stats = {"pod": pod, "elapsed": round(elapsed,1),
             "tx":0, "rx":0, "loss_pct":0.0, "rtt_avg":0.0}
    for line in output.splitlines():
        if "packets transmitted" in line:
            parts = line.split()
            try:
                stats["tx"]       = int(parts[0])
                stats["rx"]       = int(parts[3])
                stats["loss_pct"] = float(parts[5].replace("%",""))
            except (IndexError, ValueError):
                pass
        if "rtt min/avg/max" in line or "round-trip" in line:
            try:
                nums = line.split("=")[-1].strip().split("/")
                stats["rtt_avg"] = float(nums[1])
            except (IndexError, ValueError):
                pass
    return stats

def print_stats(results):
    print("\n" + "="*60)
    print(f"{'POD':<30} {'TX':>6} {'RX':>6} {'LOSS':>7} {'RTT avg':>8}")
    print("-"*60)
    total_tx = total_rx = 0
    for s in results:
        print(f"{s['pod']:<30} {s['tx']:>6} {s['rx']:>6} "
              f"{s['loss_pct']:>6.1f}% {s['rtt_avg']:>7.1f}ms")
        total_tx += s["tx"]
        total_rx += s["rx"]
    loss = round((1 - total_rx/total_tx)*100, 1) if total_tx else 0
    print("-"*60)
    print(f"{'TOTAL':<30} {total_tx:>6} {total_rx:>6} {loss:>6.1f}%")
    print("="*60)

def cmd_run(args):
    pods = get_ue_pods(args.ues)
    if not pods:
        print("[ERREUR] Aucun pod UE Running trouvé.")
        sys.exit(1)
    print(f"[INFO] {len(pods)} pods trouvés: {pods}")
    print(f"[INFO] Trafic: {args.pps} pps, {args.size}B/pkt, "
          f"{args.duration}s, target={TARGET_IP}\n")

    results = []
    with ThreadPoolExecutor(max_workers=len(pods)) as ex:
        futures = {ex.submit(run_ping, p, args.duration,
                             args.pps, args.size): p for p in pods}
        for f in as_completed(futures):
            try:
                results.append(f.result())
                pod = futures[f]
                print(f"  [OK] {pod} termine")
            except Exception as e:
                print(f"  [ERR] {futures[f]}: {e}")
    print_stats(results)

def cmd_stop(args):
    pods = get_ue_pods(99)
    if not pods:
        print("[INFO] Aucun pod UE trouvé.")
        return
    for pod in pods:
        kubectl("exec","-n",NAMESPACE,pod,"--",
                "sh","-c","pkill ping || true")
        print(f"  [STOP] {pod}")
    print(f"[INFO] ping arrêté sur {len(pods)} pods.")

def main():
    p = argparse.ArgumentParser(description="Générateur de trafic UE Free5GC")
    p.add_argument("--ues",      type=int, default=4,
                   help="Nombre de UEs à utiliser (défaut: 4)")
    p.add_argument("--duration", type=int, default=60,
                   help="Durée du trafic en secondes (défaut: 60)")
    p.add_argument("--pps",      type=int, default=200,
                   help="Paquets par seconde par UE (défaut: 200)")
    p.add_argument("--size",     type=int, default=1400,
                   help="Taille paquet en octets (défaut: 1400)")
    p.add_argument("--stop",     action="store_true",
                   help="Arrêter tout ping en cours")
    args = p.parse_args()
    if args.stop:
        cmd_stop(args)
    else:
        cmd_run(args)

if __name__ == "__main__":
    main()
