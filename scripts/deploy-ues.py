#!/usr/bin/env python3
import subprocess, json, sys, argparse, time, copy

NAMESPACE   = "free5gc"
TEMPLATE_UE = "ueransim-ue-002"
IMSI_PREFIX = "20893"  # MCC=208 MNC=93, MSIN=10 chiffres

def kubectl(*args, input_data=None, check=True):
    cmd = ["kubectl"] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, input=input_data)
    if check and r.returncode != 0:
        print(f"[ERREUR] {chr(32).join(cmd)}\n{r.stderr}", file=sys.stderr)
        sys.exit(1)
    return r

def kubectl_json(*args):
    return json.loads(kubectl(*args, "-o", "json").stdout)

def get_template():
    print(f"[INFO] Template depuis {TEMPLATE_UE}...")
    return kubectl_json("get", "deployment", TEMPLATE_UE, "-n", NAMESPACE)


def get_ue_configmap_template():
    """Recupere la ConfigMap de UE-002 comme template."""
    r = kubectl("get","configmap","-n",NAMESPACE,"-o","json", check=False)
    cms = json.loads(r.stdout).get("items",[])
    for cm in cms:
        name = cm["metadata"]["name"]
        if "ue" in name.lower() and "002" in name:
            return cm
    # Fallback: chercher par contenu
    for cm in cms:
        data = cm.get("data",{})
        for v in data.values():
            if "imsi-208930000000002" in str(v):
                return cm
    return None

def create_ue_configmap(index, cm_template):
    """Cree une ConfigMap avec le bon IMSI pour cet UE."""
    if not cm_template:
        return None
    import copy
    cm = copy.deepcopy(cm_template)
    old_imsi = "imsi-208930000000002"  # 15 chiffres
    new_imsi = f"imsi-20893{index:010d}"
    old_name = cm["metadata"]["name"]
    new_name = old_name.replace("002", f"{index:03d}")
    cm["metadata"]["name"] = new_name
    for k in ("resourceVersion","uid","creationTimestamp","managedFields"):
        cm["metadata"].pop(k, None)
    # Remplacer IMSI dans toutes les valeurs
    for key, val in cm.get("data",{}).items():
        cm["data"][key] = val.replace(old_imsi, new_imsi)
    return cm, new_name

def build_manifest(index, template):
    name = f"ueransim-ue-{index:03d}"
    imsi = f"{IMSI_PREFIX}{index:010d}"  # 15 chiffres total
    d = copy.deepcopy(template)
    meta = d["metadata"]
    meta["name"] = name
    for key in ("resourceVersion","uid","creationTimestamp","generation","managedFields","annotations"):
        meta.pop(key, None)
    meta.setdefault("labels", {})["app"] = name
    d["spec"]["selector"]["matchLabels"]["app"] = name
    d["spec"]["template"]["metadata"]["labels"]["app"] = name
    d["spec"]["template"]["metadata"].pop("creationTimestamp", None)
    d["status"] = {}
    for c in d["spec"]["template"]["spec"].get("containers", []):
        envs = c.get("env", [])
        for e in envs:
            if e.get("name") == "IMSI":
                e["value"] = imsi
                break
        else:
            envs.append({"name": "IMSI", "value": imsi})
            c["env"] = envs
        if c.get("name","").startswith("ueransim"):
            c["name"] = f"ueransim-ue-{index:03d}"
    # Mettre a jour la reference ConfigMap dans les volumes
    for vol in d["spec"]["template"]["spec"].get("volumes",[]):
        if "configMap" in vol:
            cm_name = vol["configMap"].get("name","")
            if "ue" in cm_name.lower():
                vol["configMap"]["name"] = cm_name.replace("002", f"{index:03d}")
    return d, name, imsi

def deploy_ue(index, template, dry_run=False):
    d, name, imsi = build_manifest(index, template)
    # Creer ConfigMap avec bon IMSI
    cm_template = get_ue_configmap_template()
    if cm_template:
        result = create_ue_configmap(index, cm_template)
        if result:
            cm, cm_name = result
            kubectl("apply","-f","-","-n",NAMESPACE,
                    input_data=json.dumps(cm), check=False)
    print(f"  -> Deploy {name} (IMSI={imsi})...", end=" ", flush=True)
    if dry_run: print("[DRY-RUN]"); return True
    r = kubectl("apply","-f","-","-n",NAMESPACE, input_data=json.dumps(d), check=False)
    if r.returncode == 0: print("OK"); return True
    print(f"ERREUR\n    {r.stderr.strip()}"); return False


def get_mongo_pod():
    r = kubectl("get","pod","-n",NAMESPACE,
                "-l","app.kubernetes.io/name=mongodb",
                "-o","jsonpath={.items[0].metadata.name}", check=False)
    return r.stdout.strip()

def mongosh(pod, eval_str):
    return kubectl("exec","-n",NAMESPACE,pod,"--",
                   "mongosh","free5gc","--quiet","--eval",eval_str, check=False)

def release_session(index, mongo_pod):
    """Supprimer les sessions PDU de cet UE dans MongoDB."""
    imsi = f"imsi-20893{index:010d}"
    collections = [
        "subscriptionData.contextData.amf3gppAccess",
        "subscriptionData.authenticationData.authenticationStatus",
    ]
    for coll in collections:
        mongosh(mongo_pod, f"db['{coll}'].deleteOne({{ueId:'{imsi}'}})")
    print(f"    session MongoDB libérée pour {imsi}")

def delete_ue(index, dry_run=False):
    name = f"ueransim-ue-{index:03d}"
    print(f"  -> Delete {name}...", end=" ", flush=True)
    if dry_run: print("[DRY-RUN]"); return True
    # Supprimer aussi la ConfigMap associee
    kubectl("delete","configmap",f"free5gc-free5gc-ueransim-ue-{index:03d}-configmap",
            "-n",NAMESPACE, check=False)
    r = kubectl("delete","deployment",name,"-n",NAMESPACE, check=False)
    if r.returncode == 0:
        print("OK")
        mongo_pod = get_mongo_pod()
        if mongo_pod:
            release_session(index, mongo_pod)
        return True
    if "not found" in r.stderr: print("(deja supprime)"); return True
    print(f"ERREUR\n    {r.stderr.strip()}"); return False

def wait_ready(start, count, timeout=120):
    names = [f"ueransim-ue-{i:03d}" for i in range(start, start+count)]
    print(f"\n[INFO] Attente readiness ({timeout}s max)...")
    import time as t
    deadline = t.time() + timeout
    while t.time() < deadline:
        ready = sum(1 for n in names if
            kubectl("get","deployment",n,"-n",NAMESPACE,
                "-o","jsonpath={.status.readyReplicas}",check=False).stdout.strip()=="1")
        print(f"  {ready}/{count} prets...", end="\r", flush=True)
        if ready == count: print(f"\nTous prets ({count}/{count})"); return True
        t.sleep(5)
    print(f"\nTimeout — {ready}/{count} prets"); return False

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--count",   type=int, default=4)
    p.add_argument("--start",   type=int, default=6)
    p.add_argument("--delete",  action="store_true")
    p.add_argument("--no-wait", action="store_false", dest="wait")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--status",  action="store_true")
    p.set_defaults(wait=True)
    args = p.parse_args()
    if args.status:
        print(kubectl("get","deployments","-n",NAMESPACE,check=False).stdout)
        return
    indices = list(range(args.start, args.start+args.count))
    if args.delete:
        print(f"\n[DELETE] {args.count} UEs (UE-{args.start:03d} -> UE-{indices[-1]:03d})\n")
        ok = sum(delete_ue(i, args.dry_run) for i in indices)
    else:
        print(f"\n[DEPLOY] {args.count} UEs (UE-{args.start:03d} -> UE-{indices[-1]:03d})\n")
        tmpl = get_template()
        ok = sum(deploy_ue(i, tmpl, args.dry_run) for i in indices)
        if ok > 0 and args.wait and not args.dry_run:
            wait_ready(args.start, ok, args.timeout)
    print(f"\n[RESULTAT] {ok}/{args.count}")

if __name__ == "__main__":
    main()
