# ---------------------------------------------------------------------------
# Firewall — allow HTTPS inbound only (SSH via Tailscale, not public)
# ---------------------------------------------------------------------------

resource "hcloud_firewall" "subscriptions" {
  name = "${var.server_name}-fw"

  # HTTPS
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # ICMP (ping)
  rule {
    direction  = "in"
    protocol   = "icmp"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # Tailscale UDP (WireGuard tunnel)
  rule {
    direction  = "in"
    protocol   = "udp"
    port       = "41641"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  labels = {
    app = "subscriptions"
  }
}
