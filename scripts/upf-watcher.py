#!/usr/bin/env python3
"""
UPF Watcher — surveille les changements d'état des pods UPF
et re-sync le ConfigMap SMF + redémarre le SMF si nécessaire
"""
import subprocess
import json
import time
import sys

def get_upf_ips():
    result = subprocess.run(
        ['kubectl', 'get', 'pod', '-n', 'free5gc', '-l', 'nf=upf', '-o', 'json'],
        capture_output=True, text=True)
    pods = json.loads(result.stdout)['items']
    ips = []
    for p in pods:
        if p.get('status', {}).get('phase') != 'Running':
            continue
        nets = json.loads(p['metadata']['annotations'].get(
            'k8s.v1.cni.cncf.io/network-status', '[]'))
        n4, n3 = None, None
        for n in nets:
            if 'n4' in n['name']: n4 = n['ips'][0]
            if 'n3' in n['name']: n3 = n['ips'][0]
        if n4 and n3:
            ips.append((n4, n3))
    return ips

def get_configmap_upf_ips():
    result = subprocess.run(
        ['kubectl', 'get', 'configmap', 'free5gc-free5gc-smf-configmap',
         '-n', 'free5gc', '-o', 'jsonpath={.data.smfcfg\\.yaml}'],
        capture_output=True, text=True)
    import re
    return re.findall(r'nodeID: (10\.100\.51\.\d+)', result.stdout)

def resync():
    print("[WATCHER] Re-sync IPs UPF...")
    subprocess.run(['python3', '/scripts/update-smf-upf.py'])
    
    print("[WATCHER] Restart SMF...")
    subprocess.run(['kubectl', 'rollout', 'restart',
                   'deployment', 'free5gc-free5gc-smf-smf', '-n', 'free5gc'])
    subprocess.run(['kubectl', 'wait', '--for=condition=ready',
                   'pod', '-l', 'nf=smf', '-n', 'free5gc', '--timeout=120s'])
    print("[WATCHER] Re-sync terminé ✅")

def main():
    print("[WATCHER] Démarrage surveillance UPF...")
    print("[WATCHER] Attente stabilisation initiale (30s)...")
    time.sleep(30)
    last_ips = get_upf_ips()
    print(f"[WATCHER] État initial UPF IPs: {last_ips}")
    
    while True:
        time.sleep(10)
        current_ips = get_upf_ips()
        
        if current_ips != last_ips:
            print(f"[WATCHER] Changement détecté!")
            print(f"  Avant: {last_ips}")
            print(f"  Après: {current_ips}")
            
            if current_ips:  # UPF vient de démarrer (wake-up)
                print("[WATCHER] UPF wake-up détecté — attente stabilisation...")
                time.sleep(15)  # attendre que l'UPF soit stable
                resync()
            else:
                print("[WATCHER] UPF scale-to-zero détecté")
            
            last_ips = current_ips

if __name__ == '__main__':
    main()
