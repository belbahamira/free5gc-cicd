#!/usr/bin/env python3
import csv, glob, sys, os

RESULTS = sys.argv[1] if len(sys.argv) > 1 else "results"

files = sorted(glob.glob(f"{RESULTS}/scenario-*.csv"))
if not files:
    print(f"  Aucun fichier CSV dans {RESULTS}/")
    sys.exit(0)

print()
print("=" * 70)
print(" COMPARAISON DES SCENARIOS")
print("=" * 70)
print(f"  {'Scenario':<15} {'UPF max':>8} {'SMF max':>8} {'PDU max':>8} {'BW max(bps)':>12} {'CPU SMF':>10}")
print("  " + "-" * 65)

for f in files:
    scenario = os.path.basename(f).replace("scenario-","").replace(".csv","")
    rows = list(csv.DictReader(open(f)))
    def mx(key):
        vals = [float(r[key]) for r in rows if r.get(key,"").strip()]
        return max(vals) if vals else 0
    print(f"  {scenario:<15} {mx('upf_replicas'):>8.0f} {mx('smf_replicas'):>8.0f} "
          f"{mx('pdu_sessions'):>8.0f} {mx('upf_throughput'):>12.0f} {mx('cpu_smf_mc'):>9.1f}mc")
print()
