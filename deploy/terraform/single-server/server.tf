# ---------------------------------------------------------------------------
# SSH key
# ---------------------------------------------------------------------------

resource "hcloud_ssh_key" "default" {
  name       = "${var.server_name}-key"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

resource "hcloud_server" "tidemill" {
  name         = var.server_name
  server_type  = var.server_type
  image        = var.image
  location     = var.location
  ssh_keys     = [hcloud_ssh_key.default.id]
  firewall_ids = [hcloud_firewall.tidemill.id]

  user_data = templatefile("${path.module}/cloud-init.yml", {
    domain                = var.domain
    tailscale_auth_key    = var.tailscale_auth_key
    stripe_api_key        = var.stripe_api_key
    stripe_webhook_secret = var.stripe_webhook_secret
    clerk_publishable_key = var.clerk_publishable_key
    clerk_secret_key      = var.clerk_secret_key
    clerk_jwks_url        = var.clerk_jwks_url
  })

  labels = {
    app = "tidemill"
  }
}
