output "server_ipv4" {
  description = "Public IPv4 address of the server"
  value       = hcloud_server.subscriptions.ipv4_address
}

output "server_ipv6" {
  description = "Public IPv6 address of the server"
  value       = hcloud_server.subscriptions.ipv6_address
}

output "server_status" {
  description = "Server status"
  value       = hcloud_server.subscriptions.status
}

output "domain" {
  description = "Domain name for the analytics server"
  value       = var.domain
}

output "nameservers" {
  description = "Set these nameservers at your domain registrar"
  value       = hcloud_zone.main.ns
}

output "url" {
  description = "URL of the analytics server"
  value       = "https://${var.domain}"
}

output "ssh_command" {
  description = "SSH command via Tailscale (use Tailscale machine name or IP)"
  value       = "ssh root@${var.server_name}"
}
