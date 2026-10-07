# scale.py <scenario> <trial>  -- one spike, every stage timestamped
#   room   : new pods fit on existing nodes
#   node   : existing nodes are full, a node has to be added
#   spare  : as node, but a low-priority placeholder keeps one node warm
import json, subprocess, sys, time, datetime as dt, pathlib
scen, trial = sys.argv[1], sys.argv[2]
LOAD_S = 260 if scen == "room" else 420
def k(*a, inp=None):
    return subprocess.run(["kubectl", *a], capture_output=True, text=True, input=inp).stdout
def kj(*a): return json.loads(k(*a, "-o", "json"))
def ts(s): return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()
def cond(obj, typ):
    for c in obj["status"].get("conditions", []):
        if c["type"] == typ and c["status"] == "True": return ts(c["lastTransitionTime"])
# cluster clock: stamp the start with an object the API server timestamps
name = f"t0-{scen}-{trial}"
k("delete", "configmap", name, "--ignore-not-found")
local0 = time.time(); k("create", "configmap", name); local1 = time.time()
t0 = ts(kj("get", "configmap", name)["metadata"]["creationTimestamp"])
offset = t0 - (local0 + local1) / 2          # cluster clock minus local clock, good to about a second
nodes_before = {n["metadata"]["name"] for n in kj("get", "nodes")["items"]}
pods_before = {p["metadata"]["name"] for p in kj("get", "pods", "-l", "app=web")["items"]}
assert len(pods_before) == 1 and kj("get","hpa","web")["status"].get("desiredReplicas") == 1, "not at rest, refusing to start"
lg = k("get", "pod", "-l", "app=loadgen", "-o", "jsonpath={.items[0].metadata.name}")
load = subprocess.Popen(["kubectl", "exec", lg, "--", "fortio", "load", "-qps", "0", "-c", "6", "-t", f"{LOAD_S}s", "-timeout", "60s", "-allow-initial-errors",
                         "-json", "-", "http://web/"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
first_over = first_desired = None; trace = []
while load.poll() is None:
    now = time.time() + offset - t0
    try:
        h = kj("get", "hpa", "web")["status"]
        cur = (h.get("currentMetrics") or [{}])[0].get("resource", {}).get("current", {}).get("averageUtilization")
        des = h.get("desiredReplicas")
        trace.append((round(now, 1), cur, des))
        if first_over is None and cur and cur > 50: first_over = now
        if first_desired is None and des and des > 1: first_desired = now
    except Exception: pass
    time.sleep(1)
out = load.stdout.read(); fj = json.loads(out[out.index("{"):])
hpa = kj("get", "hpa", "web")["status"]
pods = [p for p in kj("get", "pods", "-l", "app=web")["items"] if p["metadata"]["name"] not in pods_before]
ev = kj("get", "events")["items"]
def evt(reason, obj=None):
    xs = [e for e in ev if e["reason"] == reason and (obj is None or e["involvedObject"]["name"] == obj)]
    xs = [ts(e.get("firstTimestamp") or e["eventTime"][:19] + "Z") for e in xs if (e.get("firstTimestamp") or e.get("eventTime"))]
    xs = [x for x in xs if x >= t0 - 1]
    return min(xs) - t0 if xs else None
rows = []
for p in pods:
    n = p["metadata"]["name"]
    pull = [e["message"] for e in ev if e["reason"] == "Pulled" and e["involvedObject"]["name"] == n]
    rows.append(dict(pod=n, node=p["spec"].get("nodeName"), new_node=p["spec"].get("nodeName") not in nodes_before,
                     created=ts(p["metadata"]["creationTimestamp"]) - t0,
                     scheduled=(cond(p, "PodScheduled") or 0) - t0 if cond(p, "PodScheduled") else None,
                     ready=(cond(p, "Ready") or 0) - t0 if cond(p, "Ready") else None,
                     preempted_placeholder=None, pull=pull[0] if pull else None))
new_nodes = []
for n in kj("get", "nodes")["items"]:
    if n["metadata"]["name"] not in nodes_before:
        new_nodes.append(dict(node=n["metadata"]["name"], registered=ts(n["metadata"]["creationTimestamp"]) - t0,
                              ready=(cond(n, "Ready") - t0) if cond(n, "Ready") else None))
res = dict(scenario=scen, trial=trial, clock_offset=round(offset, 2), first_metric_over_target=first_over,
           first_desired_gt1=first_desired, last_scale_time=ts(hpa["lastScaleTime"]) - t0 if hpa.get("lastScaleTime") else None,
           triggered_scale_up=evt("TriggeredScaleUp"), pods=sorted(rows, key=lambda r: r["ready"] or 9e9),
           new_nodes=new_nodes, load=dict(qps=fj["ActualQPS"], codes=fj["RetCodes"]), trace=trace)
pathlib.Path("out").mkdir(exist_ok=True)
json.dump(res, open(f"out/{scen}_{trial}.json", "w"), indent=1)
rd = [r["ready"] for r in rows if r["ready"] is not None]
f = lambda x: "  -  " if x is None else f"{x:5.0f}"
print(f"{scen} #{trial}: metric>target {f(first_over)}s | desired>1 {f(first_desired)}s | lastScale {f(res['last_scale_time'])}s | "
      f"scaleUp evt {f(res['triggered_scale_up'])}s | node reg {f(new_nodes[0]['registered'] if new_nodes else None)}s ready {f(new_nodes[0]['ready'] if new_nodes else None)}s | "
      f"first pod ready {f(min(rd) if rd else None)}s last {f(max(rd) if rd else None)}s ({len(rd)}/{len(rows)} pods) | {fj['ActualQPS']:.0f} rps")
