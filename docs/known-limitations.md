# Known limitations

This is a lab: one host, one node. Some choices are deliberate simplifications.
They are listed here so nobody mistakes them for production design, with what a
production deployment would do instead.

| Area | In this lab | Consequence | In production |
|------|-------------|-------------|---------------|
| **Kafka** | One broker, replication factor 1, no persistent volume | A broker restart loses the events not yet consumed: those documents stay `pending`. The `VaultDocumentsStuckPending` alert catches it. | 3 brokers (KRaft), replication factor 3, `min.insync.replicas=2`, persistent volumes; or a managed Kafka |
| **PostgreSQL** | One instance (StatefulSet on Kubernetes) | No failover: if it stops, uploads stop | Primary + streaming replica (Patroni, CloudNativePG) or a managed database |
| **MinIO** | One server, one drive | A disk failure loses the files not yet backed up | Distributed MinIO with erasure coding (4+ drives), or managed object storage |
| **Backups** | Nightly, kept on the same host | Protects against mistakes, not against losing the server | Off-site copy (3-2-1), restore tested on a schedule |
| **TLS** | Self-signed certificate | Browser warning | Certificates from a real CA, renewed automatically (cert-manager, certbot) |
| **Authentication** | One admin account | No per-user access or audit | SSO / LDAP, roles, audit log |
| **Kubernetes secrets** | Injected as environment variables | Visible to anyone who can read the pod spec | Mounted as files, encrypted at rest, or from an external vault |
| **CI actions** | `trivy-action` referenced by branch | The action can change between two runs | Pin actions to a commit SHA |

Fixed since the first version (see git history): infected files could be
downloaded, two files with the same name overwrote each other in MinIO, a Kafka
connection was opened per upload, PostgreSQL ran as a Deployment, MinIO and ClamAV
images were not pinned on Kubernetes, alerts went nowhere, MinIO had no backup,
and Trivy never failed the build.
