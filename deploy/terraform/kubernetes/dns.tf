# ---------------------------------------------------------------------------
# DNS — register domain zone and create records pointing to the load balancer
# ---------------------------------------------------------------------------

resource "hcloud_zone" "main" {
  name = var.domain_zone
  mode = "primary"
  ttl  = 86400
}

locals {
  raw_subdomain = trimsuffix(trimsuffix(var.domain, var.domain_zone), ".")
  subdomain     = local.raw_subdomain != "" ? local.raw_subdomain : "@"
}

resource "hcloud_zone_rrset" "lb_a" {
  zone = hcloud_zone.main.id
  name = local.subdomain
  type = "A"
  ttl  = 300
  records = [{ value = module.kube_hetzner.load_balancer_public_ipv4 }]
}

resource "hcloud_zone_rrset" "lb_aaaa" {
  zone = hcloud_zone.main.id
  name = local.subdomain
  type = "AAAA"
  ttl  = 300
  records = [{ value = module.kube_hetzner.load_balancer_public_ipv6 }]
}
