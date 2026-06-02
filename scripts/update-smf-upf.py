import subprocess, json, re, tempfile, os

# Récupérer tous les pods UPF actifs et leurs IPs
result = subprocess.run(
    ['kubectl', 'get', 'pod', '-n', 'free5gc', '-l', 'nf=upf', '-o', 'json'],
    capture_output=True, text=True)
pods = json.loads(result.stdout)['items']

upf_ips = []
for p in pods:
    if p.get('status', {}).get('phase') != 'Running':
        continue
    nets = json.loads(p['metadata']['annotations'].get('k8s.v1.cni.cncf.io/network-status', '[]'))
    n3_ip, n4_ip = None, None
    for n in nets:
        if 'n3' in n['name'] and n.get('ips'): n3_ip = n['ips'][0]
        if 'n4' in n['name'] and n.get('ips'): n4_ip = n['ips'][0]
    if n4_ip and n3_ip:
        upf_ips.append((n4_ip, n3_ip))
        print(f"Pod UPF actif → N4={n4_ip} N3={n3_ip}")

if not upf_ips:
    print("❌ Aucun pod UPF Running avec annotations réseau")
    exit(1)

# Récupérer IP N4 du SMF
result = subprocess.run(
    ['kubectl', 'get', 'pod', '-n', 'free5gc', '-l', 'nf=smf', '-o', 'json'],
    capture_output=True, text=True)
smf_pods = json.loads(result.stdout)['items']
smf_n4_ip = None
for p in smf_pods:
    if p.get('status', {}).get('phase') != 'Running':
        continue
    nets = json.loads(p['metadata']['annotations'].get('k8s.v1.cni.cncf.io/network-status', '[]'))
    for n in nets:
        if 'n4' in n['name'] and n.get('ips'):
            smf_n4_ip = n['ips'][0]
            break
    if smf_n4_ip:
        break

if smf_n4_ip:
    print(f"Pod SMF actif → N4={smf_n4_ip}")
else:
    print("⚠️  IP N4 SMF non trouvée — __N4_IP__ non remplacé")

# Récupérer le ConfigMap SMF
result = subprocess.run(
    ['kubectl', 'get', 'configmap', 'free5gc-free5gc-smf-configmap', '-n', 'free5gc', '-o', 'json'],
    capture_output=True, text=True)
cm = json.loads(result.stdout)
smfcfg = cm['data']['smfcfg.yaml']

# nodeID SMF géré par init-container — ne pas écraser __N4_IP__

# Mettre à jour UPF1..4 selon les pods actifs
for i, upf_name in enumerate(['UPF1', 'UPF2', 'UPF3', 'UPF4']):
    if i < len(upf_ips):
        n4_ip, n3_ip = upf_ips[i]
        smfcfg = re.sub(rf'({upf_name}:.*?nodeID: )(None|__N4_IP__|10\.100\.51\.\d+)', rf'\g<1>{n4_ip}', smfcfg, flags=re.DOTALL)
        smfcfg = re.sub(rf'({upf_name}:.*?addr: )(None|__N4_IP__|10\.100\.51\.\d+)', rf'\g<1>{n4_ip}', smfcfg, flags=re.DOTALL)
        smfcfg = re.sub(rf'({upf_name}:.*?endpoints:\s*\n\s*- )(None|10\.100\.51\.\d+)', rf'\g<1>{n3_ip}', smfcfg, flags=re.DOTALL)
        print(f"  {upf_name} → nodeID={n4_ip} N3={n3_ip}")
    else:
        smfcfg = re.sub(rf'({upf_name}:.*?nodeID: )(None|__N4_IP__|10\.100\.51\.\d+)', rf'\g<1>None', smfcfg, flags=re.DOTALL)
        smfcfg = re.sub(rf'({upf_name}:.*?addr: )(None|__N4_IP__|10\.100\.51\.\d+)', rf'\g<1>None', smfcfg, flags=re.DOTALL)
        smfcfg = re.sub(rf'({upf_name}:.*?endpoints:\s*\n\s*- )(None|__N4_IP__|10\.100\.51\.\d+)', rf'\g<1>None', smfcfg, flags=re.DOTALL)
        print(f"  {upf_name} → None (pas de pod actif)")

cm['data']['smfcfg.yaml'] = smfcfg
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    json.dump(cm, f)
    tmpfile = f.name
subprocess.run(['kubectl', 'apply', '-f', tmpfile])
os.unlink(tmpfile)
print(f"✅ ConfigMap SMF mis à jour ({len(upf_ips)} UPF, SMF N4={smf_n4_ip})")
