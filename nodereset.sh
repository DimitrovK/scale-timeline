#!/bin/bash
# nodereset.sh -- reset the app, then remove every added node that is not hosting the placeholder
export DIGITALOCEAN_ACCESS_TOKEN=$(tr -d '\n' < ~/.config/do_token)
kubectl delete hpa web --ignore-not-found >/dev/null
kubectl scale deploy/web --replicas=1 >/dev/null
until [ "$(kubectl get pods -l app=web --no-headers 2>/dev/null | wc -l | tr -d ' ')" = "1" ]; do sleep 3; done
wn=$(kubectl get pod -l app=web -o jsonpath='{.items[0].spec.nodeName}')
grep -qx "$wn" base_nodes.txt || { echo "surviving web pod is on added node $wn, moving it"; kubectl cordon $wn >/dev/null; kubectl delete pod -l app=web >/dev/null; kubectl rollout status deploy/web --timeout=300s >/dev/null; }
if kubectl get deploy spare >/dev/null 2>&1; then kubectl rollout status deploy/spare --timeout=600s >/dev/null; sn=$(kubectl get pod -l app=spare -o jsonpath='{.items[0].spec.nodeName}'); fi
CID=$(doctl kubernetes cluster list --format ID --no-header); PID=$(doctl kubernetes cluster node-pool list $CID --format ID --no-header)
for n in $(kubectl get nodes -o jsonpath='{.items[*].metadata.name}'); do
  grep -qx "$n" base_nodes.txt && continue; [ "$n" = "${sn:-}" ] && continue
  nid=$(doctl kubernetes cluster node-pool get $CID $PID -o json | python3 -c "import sys,json;print([x['id'] for x in json.load(sys.stdin)[0]['nodes'] if x['name']=='$n'][0])")
  doctl kubernetes cluster node-pool delete-node $CID $PID $nid --skip-drain -f >/dev/null && echo "deleting $n"
done
until [ "$(kubectl get nodes --no-headers | wc -l | tr -d ' ')" -le "$(( $(grep -c . base_nodes.txt) + ${sn:+1} + 0 ))" ]; do sleep 5; done
sleep 75   # let the previous spike age out of the metrics window before an autoscaler exists to act on it
kubectl apply -f hpa.yaml >/dev/null
ok=0
for i in $(seq 1 100); do
  v=$(kubectl get hpa web -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}' 2>/dev/null)
  r=$(kubectl get deploy web -o jsonpath='{.status.replicas}')
  if [ -n "$v" ] && [ "$v" -lt 20 ] 2>/dev/null && [ "$r" = "1" ]; then ok=$((ok+1)); else ok=0; fi
  if [ $ok -ge 6 ]; then echo "reset ok, utilisation $v%, replicas $r, nodes $(kubectl get nodes --no-headers | wc -l | tr -d ' ')"; exit 0; fi
  if [ "$r" != "1" ]; then kubectl delete hpa web >/dev/null; kubectl scale deploy/web --replicas=1 >/dev/null; sleep 60; kubectl apply -f hpa.yaml >/dev/null; fi
  sleep 5
done
echo "reset TIMED OUT"; exit 1
