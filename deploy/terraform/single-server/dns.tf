# ---------------------------------------------------------------------------
# DNS — register domain zone and create records pointing to the server
# ---------------------------------------------------------------------------

resource "hcloud_zone" "main" {
  name = var.domain_zone
  ttl  = 86400
}

# Extract the subdomain part: "app.tidemill.dev" with zone "tidemill.dev" → "app"
locals {
  subdomain = trimsuffix(trimsuffix(var.domain, var.domain_zone), ".")
}

resource "hcloud_zone_rrset" "server_a" {
  zone_id = hcloud_zone.main.id
  name    = local.subdomain
  type    = "A"
  ttl     = 300
  records = [hcloud_server.subscriptions.ipv4_address]
}

resource "hcloud_zone_rrset" "server_aaaa" {
  zone_id = hcloud_zone.main.id
  name    = local.subdomain
  type    = "AAAA"
  ttl     = 300
  records = [hcloud_server.subscriptions.ipv6_address]
}
