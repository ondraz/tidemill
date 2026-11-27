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
    domain                 = var.domain
    tailscale_auth_key     = var.tailscale_auth_key
    stripe_api_key         = var.stripe_api_key
    stripe_webhook_secret  = var.stripe_webhook_secret
    clerk_publishable_key  = var.clerk_publishable_key
    clerk_secret_key       = var.clerk_secret_key
    clerk_jwks_url         = var.clerk_jwks_url
    grafana_admin_password = random_password.grafana_admin.result
  })

  labels = {
    app = "tidemill"
  }

  # The server holds the only copy of the PostgreSQL and Redpanda volumes, so
  # Terraform must never replace or destroy it.
  # - ignore_changes: changing `image` forces replacement in hcloud. Existing
  #   servers are upgraded in place (do-release-upgrade); a new default image
  #   only applies to new servers.
  # - prevent_destroy: any other change that would replace the server (e.g. a
  #   new `user_data` from a changed secret) makes plan/apply fail instead of
  #   deleting it. To rebuild on purpose, back up the data and remove this flag.
  lifecycle {
    ignore_changes  = [image]
    prevent_destroy = true
  }
}
