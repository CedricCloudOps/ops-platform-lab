# Docker Compose vs Kubernetes — they don't run together

## Key point

Docker Compose and Kubernetes are **two separate orchestrators**. Kubernetes does
**not** reuse the containers started by Docker Compose — it runs its **own**
containers through its own runtime (containerd). They share the same technology
(containers / OCI images) but **not the containers themselves**.

- **Docker Compose** — defines and runs several containers on **one host**.
- **Kubernetes** — orchestrates its **own** workloads (pods) across a **cluster**.

You pick **one** per application, not both.

> This lab runs both (the Docker Compose stack **and** k3s) on the same VM **only
> to practise**. That is not a production architecture.

## The conflict: port 80 / 443

Both want the web ports:

- Docker Compose stack → **Nginx** (reverse proxy) on 80/443
- k3s → **Traefik** (its default ingress) on 80/443

If both run, they fight for the port. Worse, `systemctl stop k3s` does **not**
remove the iptables rules k3s installed, so k3s keeps hijacking the node's
**external IP** even when it looks stopped.

## Symptom

- `curl https://localhost/` → works (Nginx replies `302 -> /login`)
- Browser on the **external IP** → `404 page not found` (plain text, ~19 bytes)

That `404 page not found` is the signature of **Traefik / Go**, not Nginx — it
means k3s is still intercepting the external IP.

## Fix (runbook)

```bash
# 1. Fully stop k3s AND flush its iptables rules + leftover containers
sudo /usr/local/bin/k3s-killall.sh

# 2. Docker re-installs its own iptables rules (k3s-killall flushed them)
sudo systemctl restart docker

# 3. Bring the stack back up
docker compose up -d

# 4. Verify — the external IP is now served by Nginx
curl -kI https://<VM_IP>/          # expect: 302 + "Server: nginx"
```

## How to avoid it

1. **Discipline** — run one orchestrator at a time. When done with k3s, always
   use `k3s-killall.sh` (not just `systemctl stop k3s`).
2. **Disable Traefik in k3s** so it never claims port 80:
   ```bash
   sudo mkdir -p /etc/rancher/k3s
   printf 'disable:\n  - traefik\n' | sudo tee /etc/rancher/k3s/config.yaml
   sudo rm -f /var/lib/rancher/k3s/server/manifests/traefik.yaml
   ```
   Then reach k8s services via NodePort (for example `:30080`).
3. **Separate machines** — in production, Compose and Kubernetes live on
   different hosts entirely.

## Diagnostic reminder — "listening != receiving"

A service can look stopped while its **leftover iptables rules** still redirect
traffic. Always check who actually answers:

```bash
curl -I http://<VM_IP>/            # who responds? (Server header, body size)
sudo ss -tlnp 'sport = :80'        # who listens on port 80
systemctl is-active k3s            # is k3s running?
```
