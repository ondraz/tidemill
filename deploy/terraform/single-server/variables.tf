variable "hcloud_token" {
  description = "Hetzner Cloud API token (from https://console.hetzner.cloud -> Security -> API Tokens)"
  type        = string
  sensitive   = true
}

variable "tailscale_auth_key" {
  description = "Tailscale auth key (from https://login.tailscale.com/admin/settings/keys)"
  type        = string
  sensitive   = true
}

variable "server_name" {
  description = "Name of the server"
  type        = string
  default     = "tidemill"
}

variable "server_type" {
  description = "Hetzner server type (cx23 = 2 vCPU, 4 GB RAM, ~EUR4.83/mo)"
  type        = string
  default     = "cx23"
}

variable "location" {
  description = "Hetzner datacenter location"
  type        = string
  default     = "fsn1" # Falkenstein, Germany. Alternatives: nbg1, hel1, ash, hil, sin
}

variable "image" {
  description = "OS image"
  type        = string
  default     = "ubuntu-24.04"
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key for server access"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "domain" {
  description = "Domain name for the analytics server (e.g. tidemill.xyz)"
  type        = string
}

variable "domain_zone" {
  description = "Parent DNS zone managed in Hetzner (e.g. example.com)"
  type        = string
}

# ── Stripe ──────────────────────────────────────────────────────────────

variable "stripe_api_key" {
  description = "Stripe API key (sk_live_... or sk_test_...)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_webhook_secret" {
  description = "Stripe webhook signing secret (whsec_...)"
  type        = string
  sensitive   = true
  default     = ""
}

# ── Clerk ───────────────────────────────────────────────────────────────

variable "clerk_publishable_key" {
  description = "Clerk publishable key (pk_live_... or pk_test_...)"
  type        = string
  default     = ""
}

variable "clerk_secret_key" {
  description = "Clerk secret key (sk_live_... or sk_test_...)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "clerk_jwks_url" {
  description = "Clerk JWKS URL for JWT verification"
  type        = string
  default     = ""
}
