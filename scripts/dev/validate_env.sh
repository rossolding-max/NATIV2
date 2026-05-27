#!/usr/bin/env bash
# Validates that .env contains the 3 vars required at boot.
# See docs/configuration.md § 5.

set -uo pipefail

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Run: cp .env.example .env  (then fill in secrets)"
    exit 1
fi

required=(POSTGRES_PASSWORD DB_MASTER_KEY ANTHROPIC_API_KEY)
missing=()

for var in "${required[@]}"; do
    val=$(grep -E "^${var}=" .env | sed -E "s/^${var}=//; s/^['\"]//; s/['\"]$//" || true)
    if [[ -z "$val" ]]; then
        missing+=("$var")
    fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: The following required env vars are missing/empty in .env:"
    for v in "${missing[@]}"; do
        echo "  - $v"
    done
    echo ""
    echo "Generate DB_MASTER_KEY via: openssl rand -base64 32"
    echo "Get ANTHROPIC_API_KEY from: https://console.anthropic.com/"
    exit 1
fi

echo "✓ All required env vars present"
