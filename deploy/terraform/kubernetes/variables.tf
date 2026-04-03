variable "hcloud_token" {
  description = "Hetzner Cloud API token"
  type        = string
  sensitive   = true
}

variable "cluster_name" {
  description = "Name of the Kubernetes cluster"
  type        = string
  default     = "subscriptions"
}

variable "location" {
  description = "Hetzner datacenter location"
  type        = string
  default     = "fsn1"
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key for node access"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "ssh_private_key_path" {
  description = "Path to SSH private key (used by kube-hetzner for provisioning)"
  type        = string
  default     = "~/.ssh/id_ed25519"
}

variable "control_plane_type" {
  description = "Server type for control plane nodes"
  type        = string
  default     = "cx23" # 2 vCPU, 4 GB RAM
}

variable "worker_type" {
  description = "Server type for worker nodes"
  type        = string
  default     = "cx33" # 4 vCPU, 8 GB RAM
}

variable "worker_count" {
  description = "Number of worker nodes"
  type        = number
  default     = 2
}

variable "domain" {
  description = "Domain name for the analytics server"
  type        = string
}

variable "domain_zone" {
  description = "Parent DNS zone managed in Hetzner"
  type        = string
}
