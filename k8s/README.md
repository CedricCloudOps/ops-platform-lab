# Document Vault on Kubernetes

Kubernetes-native manifests for the whole platform — the equivalent of the Docker
Compose stack, but orchestrated by Kubernetes (self-healing, scaling, autoscaling,
rolling updates).

> **Do not run this at the same time as the Docker Compose stack** — see
> [../docs/docker-compose-vs-kubernetes.md](../docs/docker-compose-vs-kubernetes.md).

| File | Contents |
|------|----------|
| `00-infra.yaml` | PostgreSQL, Redis, MinIO, Kafka, ClamAV (Deployments + Services + PVCs) |
| `10-app.yaml` | App Deployment + Service + **HPA**, and the worker Deployment |
| `20-ingress.yaml` | Ingress rules (needs an Ingress Controller — Traefik ships with k3s) |
| `app-deployment.yaml` | Standalone Nginx demo used to practise scaling/rollback |

## Deploy

```bash
# 0. Stop the Compose stack first (they both want port 80)
docker compose down

# 1. Build the image and import it into the k3s runtime (single-node lab, no registry)
docker build -t vault-app:v1 ./app
docker save vault-app:v1 | sudo k3s ctr images import -

# 2. Create the secret (never commit secrets to git)
sudo k3s kubectl create secret generic vault-secrets \
  --from-literal=postgres-password='YOUR_PG_PASSWORD' \
  --from-literal=minio-password='YOUR_MINIO_PASSWORD' \
  --from-literal=admin-password='YOUR_ADMIN_PASSWORD' \
  --from-literal=secret-key="$(openssl rand -hex 32)"

# 3. Apply the manifests
sudo k3s kubectl apply -f k8s/00-infra.yaml
sudo k3s kubectl apply -f k8s/10-app.yaml
sudo k3s kubectl apply -f k8s/20-ingress.yaml

# 4. Watch it come up (ClamAV takes ~2 min to load its virus database)
sudo k3s kubectl get pods -w
```

Reach the app through the Ingress on the node IP: `http://<NODE_IP>/`

## Operate

```bash
sudo k3s kubectl get pods,svc,hpa
sudo k3s kubectl scale deploy/vault-app --replicas=5      # manual scaling
sudo k3s kubectl get hpa                                  # autoscaling status
sudo k3s kubectl logs -l app=vault-worker -f               # worker (antivirus) logs
sudo k3s kubectl set image deploy/vault-app app=vault-app:v2   # rolling update
sudo k3s kubectl rollout undo deploy/vault-app             # rollback
```

## Notes

- **Images**: Kubernetes never builds images — it pulls them. On a single-node lab
  we import the image straight into containerd; on a real cluster you push it to a
  registry (GHCR, Docker Hub) and every node pulls from there.
- **Probes**: the app's `/health` endpoint backs the readiness and liveness probes.
- **HPA**: requires `resources.requests` on the containers and a metrics-server
  (k3s includes one).
- **Stateful services**: PostgreSQL and MinIO use PersistentVolumeClaims (k3s
  provides a local-path provisioner). In production these are usually **managed
  services** outside the cluster.

## Clean up

```bash
sudo k3s kubectl delete -f k8s/20-ingress.yaml -f k8s/10-app.yaml -f k8s/00-infra.yaml
sudo k3s kubectl delete secret vault-secrets
```
