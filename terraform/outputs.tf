output "public_ip" {
  description = "Public IP of the Document Vault instance"
  value       = aws_instance.vault.public_ip
}

output "ssh_command" {
  description = "SSH into the instance"
  value       = "ssh ubuntu@${aws_instance.vault.public_ip}"
}

output "app_url" {
  description = "Document Vault URL"
  value       = "https://${aws_instance.vault.public_ip}/"
}
