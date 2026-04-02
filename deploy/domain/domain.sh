#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Domain management via Namecheap API
#
# Usage:
#   ./domain.sh check <domain>                  Check availability & price
#   ./domain.sh register <domain> [years]       Register domain (default: 1 year)
#   ./domain.sh set-ns <domain> <ns1,ns2,...>   Set custom nameservers
#   ./domain.sh get-ns <domain>                 Get current nameservers
#
# Integrates with Hetzner deployment:
#   # After terraform apply, read Hetzner nameservers and set them:
#   NS=$(cd ../terraform/single-server && terraform output -json nameservers | jq -r 'join(",")')
#   ./domain.sh set-ns example.com "$NS"
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

# ---------------------------------------------------------------------------
# Validate config
# ---------------------------------------------------------------------------
: "${NAMECHEAP_API_USER:?Set NAMECHEAP_API_USER in .env}"
: "${NAMECHEAP_API_KEY:?Set NAMECHEAP_API_KEY in .env}"
: "${NAMECHEAP_CLIENT_IP:?Set NAMECHEAP_CLIENT_IP in .env}"

SANDBOX="${NAMECHEAP_SANDBOX:-false}"
if [[ "$SANDBOX" == "true" ]]; then
    API_BASE="https://api.sandbox.namecheap.com/xml.response"
else
    API_BASE="https://api.namecheap.com/xml.response"
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
namecheap_api() {
    local command=$1; shift
    local extra_params="$*"
    curl -sf "${API_BASE}?ApiUser=${NAMECHEAP_API_USER}&ApiKey=${NAMECHEAP_API_KEY}&UserName=${NAMECHEAP_API_USER}&ClientIp=${NAMECHEAP_CLIENT_IP}&Command=${command}${extra_params}"
}

# Split "example.com" into SLD="example" TLD="com"
# Split "example.co.uk" into SLD="example" TLD="co.uk"
split_domain() {
    local domain=$1
    # Known two-part TLDs
    local two_part_tlds="co.uk co.nz com.au com.br net.au org.uk org.au"
    local suffix="${domain#*.}"
    for tld in $two_part_tlds; do
        if [[ "$suffix" == "$tld" ]]; then
            SLD="${domain%%.*}"
            TLD="$tld"
            return
        fi
    done
    SLD="${domain%%.*}"
    TLD="${domain#*.}"
}

xml_attr() {
    # Extract attribute value from XML: xml_attr "Available" "$xml"
    local attr=$1 xml=$2
    echo "$xml" | grep -oP "${attr}=\"[^\"]*\"" | head -1 | sed "s/${attr}=\"//;s/\"//"
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
cmd_check() {
    local domain=${1:?Usage: domain.sh check <domain>}
    echo "Checking availability: ${domain}"

    local response
    response=$(namecheap_api "namecheap.domains.check" "&DomainList=${domain}")

    if echo "$response" | grep -q 'Status="ERROR"'; then
        echo "API error:"
        echo "$response" | grep -oP '(?<=<Error[^>]*>)[^<]+' || echo "$response"
        return 1
    fi

    local available
    available=$(xml_attr "Available" "$response")

    if [[ "$available" == "true" ]]; then
        echo "Available"
        # Try to get pricing
        split_domain "$domain"
        local price_response
        price_response=$(namecheap_api "namecheap.users.getPricing" "&ProductType=DOMAIN&ProductCategory=REGISTER&ProductName=${TLD}") 2>/dev/null || true
        local price
        price=$(echo "$price_response" | grep -oP 'YourPrice="[^"]*"' | head -1 | sed 's/YourPrice="//;s/"//') 2>/dev/null || true
        if [[ -n "${price:-}" ]]; then
            echo "Price: \$${price}/yr"
        fi
    else
        echo "Not available"
        return 1
    fi
}

cmd_register() {
    local domain=${1:?Usage: domain.sh register <domain> [years]}
    local years=${2:-1}

    # Validate contact info
    : "${CONTACT_FIRST_NAME:?Set CONTACT_FIRST_NAME in .env}"
    : "${CONTACT_LAST_NAME:?Set CONTACT_LAST_NAME in .env}"
    : "${CONTACT_ADDRESS:?Set CONTACT_ADDRESS in .env}"
    : "${CONTACT_CITY:?Set CONTACT_CITY in .env}"
    : "${CONTACT_STATE:?Set CONTACT_STATE in .env}"
    : "${CONTACT_POSTAL_CODE:?Set CONTACT_POSTAL_CODE in .env}"
    : "${CONTACT_COUNTRY:?Set CONTACT_COUNTRY in .env}"
    : "${CONTACT_PHONE:?Set CONTACT_PHONE in .env}"
    : "${CONTACT_EMAIL:?Set CONTACT_EMAIL in .env}"

    split_domain "$domain"

    echo "Registering ${domain} for ${years} year(s)..."
    if [[ "$SANDBOX" != "true" ]]; then
        echo "This will charge your Namecheap account."
        read -rp "Continue? [y/N] " confirm
        [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Cancelled."; return 1; }
    fi

    # Build contact params for all 4 roles
    local contact_params=""
    for role in Registrant Tech Admin AuxBilling; do
        contact_params+="&${role}FirstName=${CONTACT_FIRST_NAME}"
        contact_params+="&${role}LastName=${CONTACT_LAST_NAME}"
        contact_params+="&${role}Address1=${CONTACT_ADDRESS}"
        contact_params+="&${role}City=${CONTACT_CITY}"
        contact_params+="&${role}StateProvince=${CONTACT_STATE}"
        contact_params+="&${role}PostalCode=${CONTACT_POSTAL_CODE}"
        contact_params+="&${role}Country=${CONTACT_COUNTRY}"
        contact_params+="&${role}Phone=${CONTACT_PHONE}"
        contact_params+="&${role}EmailAddress=${CONTACT_EMAIL}"
    done

    local response
    response=$(namecheap_api "namecheap.domains.create" \
        "&DomainName=${domain}&Years=${years}${contact_params}&AddFreeWhoisguard=yes&WGEnabled=yes")

    if echo "$response" | grep -q 'Status="OK"'; then
        echo "Registered ${domain}"
        local expiry
        expiry=$(xml_attr "DomainDetails" "$response" 2>/dev/null) || true
        echo "WHOIS privacy: enabled"
    else
        echo "Registration failed:"
        echo "$response" | grep -oP '(?<=<Error[^>]*>)[^<]+' || echo "$response"
        return 1
    fi
}

cmd_set_ns() {
    local domain=${1:?Usage: domain.sh set-ns <domain> <ns1,ns2,...>}
    local nameservers=${2:?Provide comma-separated nameservers}

    split_domain "$domain"

    echo "Setting nameservers for ${domain}: ${nameservers}"

    local response
    response=$(namecheap_api "namecheap.domains.dns.setCustom" \
        "&SLD=${SLD}&TLD=${TLD}&Nameservers=${nameservers}")

    if echo "$response" | grep -q 'Status="OK"'; then
        echo "Nameservers updated"
        echo ""
        echo "Hetzner DNS will handle resolution once propagation completes (up to 48h)."
        echo "Verify: dig +short NS ${domain}"
    else
        echo "Failed to set nameservers:"
        echo "$response" | grep -oP '(?<=<Error[^>]*>)[^<]+' || echo "$response"
        return 1
    fi
}

cmd_get_ns() {
    local domain=${1:?Usage: domain.sh get-ns <domain>}

    split_domain "$domain"

    local response
    response=$(namecheap_api "namecheap.domains.dns.getList" "&SLD=${SLD}&TLD=${TLD}")

    if echo "$response" | grep -q 'Status="OK"'; then
        local is_custom
        is_custom=$(xml_attr "IsUsingOurDNS" "$response")
        if [[ "$is_custom" == "false" ]]; then
            echo "Custom nameservers:"
        else
            echo "Namecheap default nameservers:"
        fi
        echo "$response" | grep -oP '(?<=<Nameserver>)[^<]+' | while read -r ns; do
            echo "  ${ns}"
        done
    else
        echo "Failed to get nameservers:"
        echo "$response" | grep -oP '(?<=<Error[^>]*>)[^<]+' || echo "$response"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
case "${1:-help}" in
    check)        shift; cmd_check "$@" ;;
    register)     shift; cmd_register "$@" ;;
    set-ns)       shift; cmd_set_ns "$@" ;;
    get-ns)       shift; cmd_get_ns "$@" ;;
    help|--help|-h)
        echo "Usage: domain.sh <command> [args]"
        echo ""
        echo "Commands:"
        echo "  check <domain>                  Check availability & price"
        echo "  register <domain> [years]       Register domain (default: 1 year)"
        echo "  set-ns <domain> <ns1,ns2,...>   Set custom nameservers"
        echo "  get-ns <domain>                 Get current nameservers"
        echo ""
        echo "Typical flow with Hetzner deployment:"
        echo "  1. ./domain.sh check example.com"
        echo "  2. ./domain.sh register example.com"
        echo "  3. cd ../terraform/single-server && terraform apply"
        echo "  4. NS=\$(terraform output -json nameservers | jq -r 'join(\",\")')"
        echo "  5. cd ../../domain && ./domain.sh set-ns example.com \"\$NS\""
        ;;
    *)
        echo "Unknown command: $1 (try --help)" >&2
        exit 1
        ;;
esac
