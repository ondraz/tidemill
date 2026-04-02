# ---------------------------------------------------------------------------
# Domain nameserver delegation — points Namecheap domain to Hetzner DNS
#
# This manages the registrar-side nameserver config. The Hetzner-side zone
# and DNS records are managed by the single-server or kubernetes configs.
#
# Flow:
#   1. Register domain on Namecheap (via deploy/domain/domain.sh or web UI)
#   2. Deploy infrastructure: cd ../single-server && terraform apply
#   3. Delegate DNS:          cd ../domain && terraform apply
# ---------------------------------------------------------------------------

terraform {
  required_version = ">= 1.5"

  required_providers {
    namecheap = {
      source  = "namecheap/namecheap"
      version = "~> 2.0"
    }
  }
}

provider "namecheap" {
  user_name   = var.namecheap_user
  api_user    = var.namecheap_user
  api_key     = var.namecheap_api_key
  client_ip   = var.namecheap_client_ip
  use_sandbox = var.namecheap_sandbox
}

# ---------------------------------------------------------------------------
# Set domain nameservers to Hetzner DNS
# ---------------------------------------------------------------------------

resource "namecheap_domain_records" "main" {
  domain      = var.domain_zone
  nameservers = var.nameservers
}
