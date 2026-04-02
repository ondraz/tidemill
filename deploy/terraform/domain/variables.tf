variable "namecheap_user" {
  description = "Namecheap username"
  type        = string
}

variable "namecheap_api_key" {
  description = "Namecheap API key (from https://ap.www.namecheap.com/settings/tools/apiaccess/)"
  type        = string
  sensitive   = true
}

variable "namecheap_client_ip" {
  description = "Your public IP (must be whitelisted in Namecheap API access)"
  type        = string
}

variable "namecheap_sandbox" {
  description = "Use Namecheap sandbox API for testing"
  type        = bool
  default     = false
}

variable "domain_zone" {
  description = "Root domain registered on Namecheap (e.g. tidemill.dev)"
  type        = string
}

variable "nameservers" {
  description = "Hetzner nameservers — from: cd ../single-server && terraform output nameservers"
  type        = list(string)
}
