output "kubeconfig_path" {
  description = "Path to the generated kubeconfig file"
  value       = module.kube_hetzner.kubeconfig_file
}

output "load_balancer_ipv4" {
  description = "Public IPv4 of the load balancer"
  value       = module.kube_hetzner.load_balancer_public_ipv4
}

output "nameservers" {
  description = "Set these nameservers at your domain registrar"
  value       = hcloud_zone.main.ns
}

output "url" {
  description = "URL of the analytics server"
  value       = "https://${var.domain}"
}
