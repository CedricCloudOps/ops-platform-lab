# Terraform — provision the Document Vault infrastructure

Provisions an AWS EC2 instance (Ubuntu 24.04) with a security group (SSH/80/443)
and bootstraps Docker + clones this repo via `user_data`.

## Usage

```bash
cd terraform
terraform init
terraform validate                 # no credentials needed
terraform plan  -var="key_name=my-keypair"   # needs AWS credentials
terraform apply -var="key_name=my-keypair"
```

After `apply`, SSH in (see the `ssh_command` output), create the Docker secrets
(`secrets/README.md`), then run `docker compose up -d`.

```bash
terraform destroy   # tear everything down
```

## Notes

- **State**: this example keeps Terraform state locally. For a team, use a remote
  backend (e.g. an S3 bucket + DynamoDB lock).
- **Credentials**: `apply`/`plan` read AWS credentials from the environment
  (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) or `~/.aws/credentials`.
- `terraform validate` runs in CI on every push — see `.github/workflows/ci.yml`.
