variable "region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-west-1"
}

variable "name" {
  description = "Name tag / prefix for the resources"
  type        = string
  default     = "document-vault"
}

variable "instance_type" {
  description = "EC2 instance size (the stack needs ~2 GB RAM)"
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Name of an existing EC2 key pair for SSH access"
  type        = string
}

variable "ssh_cidr" {
  description = "CIDR allowed to reach SSH (lock this down to your IP)"
  type        = string
  default     = "0.0.0.0/0"
}

variable "repo_url" {
  description = "Git URL of the stack to clone on boot"
  type        = string
  default     = "https://github.com/CedricCloudOps/ops-platform-lab.git"
}
