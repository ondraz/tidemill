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

resource "hcloud_server" "subscriptions" {
  name         = var.server_name
  server_type  = var.server_type
  image        = var.image
  location     = var.location
  ssh_keys     = [hcloud_ssh_key.default.id]
  firewall_ids = [hcloud_firewall.subscriptions.id]

  user_data = templatefile("${path.module}/cloud-init.yml", {
    domain             = var.domain
    tailscale_auth_key = var.tailscale_auth_key
  })

  labels = {
    app = "subscriptions"
  }
}
