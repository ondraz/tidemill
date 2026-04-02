output "domain" {
  description = "Domain delegated to Hetzner DNS"
  value       = var.domain_zone
}

output "nameservers" {
  description = "Nameservers set at registrar"
  value       = var.nameservers
}
