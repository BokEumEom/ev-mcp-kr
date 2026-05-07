#!/usr/bin/env bash
# Build .mcpb bundles for both manifest variants.
#
# Usage:
#   bash scripts/build_mcpb.sh                # builds both
#   bash scripts/build_mcpb.sh native         # native Python only
#   bash scripts/build_mcpb.sh wsl            # Windows + WSL bridge only
#
# Output:
#   /tmp/ev-mcp.mcpb           — native Python (Linux/Mac/Windows-with-deps)
#   /tmp/ev-mcp-wsl.mcpb       — Windows Claude Desktop ↔ WSL Ubuntu venv

set -euo pipefail

cd "$(dirname "$0")/.."

VARIANT="${1:-both}"
MAIN_MANIFEST="manifest.json"
WSL_MANIFEST="manifest-windows-wsl.json"

build_one() {
    local manifest_src="$1"
    local output="$2"

    # Save current manifest, swap in the variant, pack, restore.
    cp "$MAIN_MANIFEST" "${MAIN_MANIFEST}.bak"
    trap 'mv "${MAIN_MANIFEST}.bak" "$MAIN_MANIFEST" 2>/dev/null || true' EXIT

    if [[ "$manifest_src" != "$MAIN_MANIFEST" ]]; then
        cp "$manifest_src" "$MAIN_MANIFEST"
    fi

    rm -f "$output"
    mcpb pack . "$output"

    mv "${MAIN_MANIFEST}.bak" "$MAIN_MANIFEST"
    trap - EXIT
    echo "  → $output"
}

case "$VARIANT" in
    native)
        echo "Building native variant…"
        build_one "$MAIN_MANIFEST" "/tmp/ev-mcp.mcpb"
        ;;
    wsl)
        echo "Building Windows+WSL variant…"
        build_one "$WSL_MANIFEST" "/tmp/ev-mcp-wsl.mcpb"
        ;;
    both)
        echo "Building native variant…"
        build_one "$MAIN_MANIFEST" "/tmp/ev-mcp.mcpb"
        echo "Building Windows+WSL variant…"
        build_one "$WSL_MANIFEST" "/tmp/ev-mcp-wsl.mcpb"
        ;;
    *)
        echo "Unknown variant: $VARIANT (use: native | wsl | both)" >&2
        exit 2
        ;;
esac

echo "Done."
