# Secrets

Passwords are injected as **Docker secrets** — mounted as files in
`/run/secrets/` inside the containers, never exposed as environment variables
(so they don't leak through `docker inspect`).

Create these two files locally (they are git-ignored — **never commit real secrets**):

```bash
mkdir -p secrets
printf '%s' "your-postgres-password" > secrets/postgres_password.txt
printf '%s' "your-minio-password"    > secrets/minio_password.txt   # min. 8 chars
```

| File | Used by | Env convention |
|------|---------|----------------|
| `postgres_password.txt` | postgres, app, worker | `POSTGRES_PASSWORD_FILE` |
| `minio_password.txt` | minio, app, worker | `MINIO_ROOT_PASSWORD_FILE` / `MINIO_PASSWORD_FILE` |
| `admin_password.txt` | app (login) | `ADMIN_PASSWORD_FILE` |
| `secret_key.txt` | app (Flask session signing) | `SECRET_KEY_FILE` |

```bash
printf '%s' "your-admin-login-password" > secrets/admin_password.txt
openssl rand -hex 32                     > secrets/secret_key.txt
```

> If PostgreSQL was already initialised, keep the **same** password it was
> created with (PostgreSQL sets the password only on first init).
