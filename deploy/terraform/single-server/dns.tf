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
  zone    = hcloud_zone.main.id
  name    = local.subdomain
  type    = "A"
  ttl     = 300
  records = [{ value = hcloud_server.tidemill.ipv4_address }]
}

resource "hcloud_zone_rrset" "server_aaaa" {
  zone    = hcloud_zone.main.id
  name    = local.subdomain
  type    = "AAAA"
  ttl     = 300
  records = [{ value = hcloud_server.tidemill.ipv6_address }]
}

# app.<domain> — React dashboard. The root domain serves the public landing
# page; the SPA lives on this subdomain so its API calls stay same-origin.
locals {
  app_subdomain     = local.subdomain == "@" ? "app" : "app.${local.subdomain}"
  grafana_subdomain = local.subdomain == "@" ? "grafana" : "grafana.${local.subdomain}"
}

resource "hcloud_zone_rrset" "app_a" {
  zone    = hcloud_zone.main.id
  name    = local.app_subdomain
  type    = "A"
  ttl     = 300
  records = [{ value = hcloud_server.tidemill.ipv4_address }]
}

resource "hcloud_zone_rrset" "app_aaaa" {
  zone    = hcloud_zone.main.id
  name    = local.app_subdomain
  type    = "AAAA"
  ttl     = 300
  records = [{ value = hcloud_server.tidemill.ipv6_address }]
}

# ---------------------------------------------------------------------------
# Email forwarding — ImprovMX (ondra@tidemill.xyz → ondra.zahradnik@gmail.com)
# After applying, add the alias in the ImprovMX dashboard at improvmx.com.
# ---------------------------------------------------------------------------

resource "hcloud_zone_rrset" "email_mx" {
  zone = hcloud_zone.main.id
  name = "@"
  type = "MX"
  ttl  = 300
  records = [
    { value = "10 mx1.improvmx.com." },
    { value = "20 mx2.improvmx.com." },
  ]
}

resource "hcloud_zone_rrset" "email_spf" {
  zone    = hcloud_zone.main.id
  name    = "@"
  type    = "TXT"
  ttl     = 300
  records = [{ value = "\"v=spf1 include:spf.improvmx.com ~all\"" }]
}

# grafana.<domain> — observability UI. Tempo, Loki, Prometheus, OTEL Collector
# stay on the internal docker network; only Grafana is publicly reachable.
resource "hcloud_zone_rrset" "grafana_a" {
  zone    = hcloud_zone.main.id
  name    = local.grafana_subdomain
  type    = "A"
  ttl     = 300
  records = [{ value = hcloud_server.tidemill.ipv4_address }]
}

resource "hcloud_zone_rrset" "grafana_aaaa" {
  zone    = hcloud_zone.main.id
  name    = local.grafana_subdomain
  type    = "AAAA"
  ttl     = 300
  records = [{ value = hcloud_server.tidemill.ipv6_address }]
}
