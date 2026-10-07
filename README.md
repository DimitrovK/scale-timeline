# scale-timeline

How long Kubernetes takes to answer a traffic spike, timed stage by stage.

One pod, one burst of load, and a timestamp on every step until extra pods are serving:
when the HorizontalPodAutoscaler first acts, when pods are created, scheduled and ready,
and, when the cluster is full, when a node is requested, registers and becomes Ready.

Run on DigitalOcean Kubernetes 1.36.3, `s-2vcpu-4gb` nodes, pool autoscaling 2 to 5, fra1,
on 2026-10-06. Default autoscaler and metrics-server settings.

## Results (seconds from the start of the load)

| scenario | trials | first extra pod ready, median | range |
|---|---|---|---|
| room on existing nodes | 8 | 30 | 27 to 46 |
| a node has to be added | 4 | 249 | 232 to 276 |
| low-priority placeholder keeps a spare node | 3 | 49 | 47 to 75 |

Raw per-trial output, including the autoscaler trace, is in `out/`.

## Files

- `app.yaml`, `hpa.yaml` - the app (`registry.k8s.io/hpa-example`), service, load generator and autoscaler
- `scale.py <room|node|spare> <trial>` - runs one spike and records every stage
- `reset.sh`, `nodereset.sh` - return to one pod and a settled metric between trials
- `ballast.py` - fills the current nodes so the next pod cannot fit
- `spare.yaml` - the negative-priority placeholder

## Things that went wrong

- An HTTP readiness probe against the CPU-burning page was enough load to scale the app to five pods on its own.
- Three early trials started while stale metrics from the previous spike were still in the window. They are excluded; `reset.sh` now waits them out and `scale.py` refuses to start unless one pod is running.
- `fortio` aborts if its warm-up request takes over three seconds, so it needs `-timeout` and `-allow-initial-errors` against a saturated pod.
