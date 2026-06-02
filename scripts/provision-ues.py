#!/usr/bin/env python3
"""
provision-ues.py — Provisionner des abonnes dans Free5GC via MongoDB
Usage:
  python3 provision-ues.py --count 50 --start 6
  python3 provision-ues.py --delete --start 6 --count 50
  python3 provision-ues.py --list
"""
import subprocess, sys, argparse, json

NAMESPACE   = "free5gc"
MONGO_LABEL = "app.kubernetes.io/name=mongodb"
DB          = "free5gc"
COLLECTION  = "subscriptionData.authenticationData.authenticationSubscription"

# Template copie exacte des abonnes existants
TEMPLATE = {
    "permanentKey": {
        "encryptionAlgorithm": 0,
        "encryptionKey": 0,
        "permanentKeyValue": "8baf473f2f8fd09487cccbd7097c6862"
    },
    "sequenceNumber": "000000000023",
    "authenticationManagementField": "8000",
    "milenage": {"op": {"encryptionAlgorithm": 0, "encryptionKey": 0, "opValue": ""}},
    "opc": {
        "encryptionAlgorithm": 0,
        "encryptionKey": 0,
        "opcValue": "8e27b6af0e692e750f32667a3b14605d"
    },
    "authenticationMethod": "5G_AKA"
}

# Collections supplementaires a provisionner (meme pattern que les abonnes existants)
EXTRA_COLLECTIONS = [
    ("subscriptionData.provisionedData.smData",
     {"singleNssai": {"sst": 1, "sd": "010203"},
      "dnnConfigurations": {
        "internet": {"pduSessionTypes": {"defaultSessionType": "IPV4", "allowedSessionTypes": ["IPV4"]},
                     "sscModes": {"defaultSscMode": "SSC_MODE_1", "allowedSscModes": ["SSC_MODE_2","SSC_MODE_3"]},
                     "5gQosProfile": {"5qi": 9, "arp": {"preemptCap": "", "preemptVuln": "", "priorityLevel": 8}, "priorityLevel": 8},
                     "sessionAmbr": {"uplink": "200 Mbps", "downlink": "100 Mbps"}},
        "internet2": {"pduSessionTypes": {"defaultSessionType": "IPV4", "allowedSessionTypes": ["IPV4"]},
                      "sscModes": {"defaultSscMode": "SSC_MODE_1", "allowedSscModes": ["SSC_MODE_2","SSC_MODE_3"]},
                      "5gQosProfile": {"5qi": 9, "arp": {"preemptCap": "", "preemptVuln": "", "priorityLevel": 8}, "priorityLevel": 8},
                      "sessionAmbr": {"uplink": "200 Mbps", "downlink": "100 Mbps"}}},
      "servingPlmnId": "20893"}),
    ("policyData.ues.amData",
     {"subscCats": ["free5gc"]}),
    ("policyData.ues.smData",
     {"smPolicySnssaiData": {
       "01010203": {"snssai": {"sst": 1, "sd": "010203"},
                    "smPolicyDnnData": {"internet": {"dnn": "internet"}, "internet2": {"dnn": "internet2"}}},
       "01112233": {"snssai": {"sst": 1, "sd": "112233"},
                    "smPolicyDnnData": {"internet": {"dnn": "internet"}, "internet2": {"dnn": "internet2"}}}}}),
    # collections originales
    ("subscriptionData.provisionedData.amData",
     {"gpsis": ["msisdn-0900000000"], "nssai": {"defaultSingleNssais": [{"sst": 1, "sd": "010203"}], "singleNssais": [{"sst": 1, "sd": "010203"}]}, "subscribedUeAmbr": {"downlink": "2 Gbps", "uplink": "1 Gbps"}}),
    ("subscriptionData.provisionedData.smData",
     [{"singleNssai": {"sst": 1, "sd": "010203"}, "dnnConfigurations": {"internet": {"pduSessionTypes": {"allowedSessionTypes": ["IPV4"], "defaultSessionType": "IPV4"}, "sscModes": {"allowedSscModes": ["SSC_MODE_2", "SSC_MODE_3"], "defaultSscMode": "SSC_MODE_1"}, "sessionAmbr": {"downlink": "200 Mbps", "uplink": "100 Mbps"}, "5gQosProfile": {"5qi": 9, "arp": {"priorityLevel": 8, "preemptCap": "NOT_PREEMPT", "preemptVuln": "NOT_PREEMPTABLE"}, "priorityLevel": 8}}}}]),
    ("subscriptionData.provisionedData.smfSelectionSubscriptionData",
     {"subscribedSnssaiInfos": {"01010203": {"dnnInfos": [{"dnn": "internet"}]}}}),
    ("subscriptionData.provisionedData.uePolicyData",
     {"subsSessAmbr": {"downlink": "2 Gbps", "uplink": "1 Gbps"}, "subsUeSliceMbrList": {"01010203": {"sliceSessionAmbrs": {"downlink": "1 Gbps", "uplink": "500 Mbps"}}}}),
]

def get_mongo_pod():
    r = subprocess.run(
        ["kubectl","get","pod","-n",NAMESPACE,"-l",MONGO_LABEL,
         "-o","jsonpath={.items[0].metadata.name}"],
        capture_output=True, text=True)
    pod = r.stdout.strip()
    if not pod:
        print("[ERREUR] Pod MongoDB introuvable", file=sys.stderr)
        sys.exit(1)
    return pod

def mongosh(pod, eval_str):
    r = subprocess.run(
        ["kubectl","exec","-n",NAMESPACE,pod,"--",
         "mongosh",DB,"--quiet","--eval", eval_str],
        capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip()

def imsi_str(index):
    return f"imsi-20893000000{index:04d}"

def provision_one(pod, index):
    imsi = imsi_str(index)
    doc = dict(TEMPLATE)
    doc["ueId"] = imsi
    doc_json = json.dumps(doc).replace("'", "\'")

    # Inserer seulement si absent
    eval_str = (
        f"var d={doc_json}; "
        f"var r=db['{COLLECTION}'].updateOne({{ueId:d.ueId}},{{$setOnInsert:d}},{{upsert:true}}); "
        f"print(r.upsertedCount>0?'inserted':'exists');"
    )
    out, err = mongosh(pod, eval_str)

    # Collections supplementaires
    for coll, data in EXTRA_COLLECTIONS:
        data_copy = dict(data) if isinstance(data, dict) else list(data)
        if isinstance(data_copy, dict):
            data_copy["ueId"] = imsi
        elif isinstance(data_copy, list):
            for item in data_copy:
                item["ueId"] = imsi
        d_json = json.dumps(data_copy).replace("'", "\'")
        mongosh(pod, f"db['{coll}'].updateOne({{ueId:'{imsi}'}},{{$setOnInsert:{d_json}}},{{upsert:true}})")

    return out.strip()

def delete_one(pod, index):
    imsi = imsi_str(index)
    eval_str = f"var r=db['{COLLECTION}'].deleteOne({{ueId:'{imsi}'}}); print(r.deletedCount);"
    out, _ = mongosh(pod, eval_str)
    # Supprimer aussi les autres collections
    for coll, _ in EXTRA_COLLECTIONS:
        mongosh(pod, f"db['{coll}'].deleteOne({{ueId:'{imsi}'}});")
    return out.strip()

def list_subscribers(pod):
    out, _ = mongosh(pod,
        f"db['{COLLECTION}'].find({{}},{{ueId:1,_id:0}}).sort({{ueId:1}}).toArray()")
    print("[INFO] Abonnes provisonnes:\n" + out)

def main():
    p = argparse.ArgumentParser(description="Provisionner abonnes Free5GC dans MongoDB")
    p.add_argument("--count",  type=int, default=10)
    p.add_argument("--start",  type=int, default=6)
    p.add_argument("--delete", action="store_true")
    p.add_argument("--list",   action="store_true")
    args = p.parse_args()

    pod = get_mongo_pod()
    print(f"[INFO] MongoDB pod: {pod}")

    if args.list:
        list_subscribers(pod)
        return

    indices = list(range(args.start, args.start + args.count))

    if args.delete:
        print(f"\n[DELETE] {args.count} abonnes (IMSI ...{args.start:04d} -> ...{indices[-1]:04d})\n")
        for i in indices:
            r = delete_one(pod, i)
            status = "OK" if r == "1" else "absent"
            print(f"  {imsi_str(i)} -> {status}")
    else:
        print(f"\n[PROVISION] {args.count} abonnes (IMSI ...{args.start:04d} -> ...{indices[-1]:04d})\n")
        for i in indices:
            r = provision_one(pod, i)
            print(f"  {imsi_str(i)} -> {r}")

    print(f"\n[FIN] {args.count} abonnes traites.")

if __name__ == "__main__":
    main()
