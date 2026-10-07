# ballast.py -- fill every current node so that less than one app pod (200m) of CPU is left on each
import json, subprocess
def kj(*a): return json.loads(subprocess.run(["kubectl", *a, "-o", "json"], capture_output=True, text=True).stdout)
def milli(v): return int(v[:-1]) if v.endswith("m") else int(float(v) * 1000)
pods = kj("get", "pods", "-A")["items"]; base = []
for n in kj("get", "nodes")["items"]:
    name = n["metadata"]["name"]; base.append(name)
    alloc = milli(n["status"]["allocatable"]["cpu"])
    used = sum(milli(c.get("resources", {}).get("requests", {}).get("cpu", "0"))
               for p in pods if p["spec"].get("nodeName") == name and p["status"]["phase"] in ("Running", "Pending")
               for c in p["spec"]["containers"])
    want = alloc - used - 120
    print(f"{name}: allocatable {alloc}m, requested {used}m, ballast {want}m")
    man = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": f"ballast-{name}", "labels": {"app": "ballast"}},
           "spec": {"nodeName": name, "terminationGracePeriodSeconds": 0,
                    "containers": [{"name": "pause", "image": "registry.k8s.io/pause:3.10",
                                    "resources": {"requests": {"cpu": f"{want}m"}}}]}}
    subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(man), text=True, capture_output=True)
open("base_nodes.txt", "w").write("\n".join(base))
