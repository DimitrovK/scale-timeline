#!/bin/bash
# reset.sh -- back to one pod, a fresh autoscaler, and a metric that has settled
kubectl delete hpa web --ignore-not-found >/dev/null
kubectl scale deploy/web --replicas=1 >/dev/null
until [ "$(kubectl get pods -l app=web --no-headers 2>/dev/null | wc -l | tr -d ' ')" = "1" ]; do sleep 3; done
kubectl rollout status deploy/web --timeout=180s >/dev/null
sleep 75   # let the previous spike age out of the metrics window before an autoscaler exists to act on it
kubectl apply -f hpa.yaml >/dev/null
ok=0
for i in $(seq 1 100); do
  v=$(kubectl get hpa web -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}' 2>/dev/null)
  r=$(kubectl get deploy web -o jsonpath='{.status.replicas}')
  if [ -n "$v" ] && [ "$v" -lt 20 ] 2>/dev/null && [ "$r" = "1" ]; then ok=$((ok+1)); else ok=0; fi
  if [ $ok -ge 6 ]; then echo "reset ok, utilisation $v%, replicas $r"; exit 0; fi
  if [ "$r" != "1" ]; then kubectl delete hpa web >/dev/null; kubectl scale deploy/web --replicas=1 >/dev/null; sleep 60; kubectl apply -f hpa.yaml >/dev/null; fi
  sleep 5
done
echo "reset TIMED OUT"; exit 1
