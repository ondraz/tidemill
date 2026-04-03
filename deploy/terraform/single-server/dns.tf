# ---------------------------------------------------------------------------
# DNS — register domain zone and create records pointing to the server
# ---------------------------------------------------------------------------

resource "hcloud_zone" "main" {
  name = var.domain_zone
  mode = "primary"
  ttl  = 86400
}

# Extract the subdomain part: "app.tidemill.xyz" with zone "tidemill.xyz" → "app"
locals {
  raw_subdomain = trimsuffix(trimsuffix(var.domain, var.domain_zone), ".")
  subdomain     = local.raw_subdomain != "" ? local.raw_subdomain : "@"
}

resource "hcloud_zone_rrset" "server_a" {
  zone = hcloud_zone.main.id
  name = local.subdomain
  type = "A"
  ttl  = 300
  records = [{ value = hcloud_server.subscriptions.ipv4_address }]
}

resource "hcloud_zone_rrset" "server_aaaa" {
  zone = hcloud_zone.main.id
  name = local.subdomain
  type = "AAAA"
  ttl  = 300
  records = [{ value = hcloud_server.subscriptions.ipv6_address }]
}
