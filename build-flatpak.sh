#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# build-flatpak.sh — Build and optionally install the Neural Monolith Flatpak.
#
# Usage
# -----
#   ./build-flatpak.sh [options]
#
# Options
#   -i, --install      Install the Flatpak for the current user after building.
#   -r, --run          Run the app immediately after installing.
#   -c, --clean        Delete the build directory before building.
#   -o, --output DIR   Directory to place the finished .flatpak bundle
#                      (default: ./dist).
#   -h, --help         Print this help and exit.
#
# Prerequisites
# -------------
#   flatpak            https://flatpak.org/setup/
#   flatpak-builder    usually packaged with flatpak or as a separate package
#   org.gnome.Platform + org.gnome.Sdk runtime (version 50):
#       flatpak remote-add --if-not-exists flathub \
#           https://flathub.org/repo/flathub.flatpakrepo
#       flatpak install flathub org.gnome.Platform//50 org.gnome.Sdk//50
#
# The finished bundle is exported to <output>/io.github.robertbiv.LinuxAiNpuAssistant.flatpak
# and can be shared / sideloaded with:
#   flatpak install --user <bundle>.flatpak

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────

APP_ID="io.github.robertbiv.LinuxAiNpuAssistant"
MANIFEST="packaging/${APP_ID}.yml"
BUILD_DIR=".flatpak-build"
REPO_DIR=".flatpak-repo"
OUTPUT_DIR="dist"
GNOME_RUNTIME_VERSION="50"
INSTALL=false
RUN_APP=false
CLEAN=false

# ── Colours ───────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
CYN='\033[0;36m'
RST='\033[0m'

info()  { echo -e "${CYN}[INFO]${RST}  $*"; }
ok()    { echo -e "${GRN}[OK]${RST}    $*"; }
warn()  { echo -e "${YLW}[WARN]${RST}  $*"; }
die()   { echo -e "${RED}[ERROR]${RST} $*" >&2; exit 1; }

# ── Argument parsing ──────────────────────────────────────────────────────────

usage() {
    sed -n '/^# Usage/,/^$/p' "$0" | sed 's/^# \?//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -i|--install) INSTALL=true ;;
        -r|--run)     RUN_APP=true; INSTALL=true ;;
        -c|--clean)   CLEAN=true ;;
        -o|--output)  OUTPUT_DIR="${2:?--output requires a directory}"; shift ;;
        -h|--help)    usage ;;
        *) die "Unknown option: $1  (use --help for usage)" ;;
    esac
    shift
done

# ── Preflight checks ──────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

info "Working directory: $(pwd)"

[[ -f "$MANIFEST" ]] || die "Manifest not found: $MANIFEST"

check_cmd() {
    command -v "$1" &>/dev/null || die "$1 is not installed.  $2"
}

check_cmd flatpak \
    "Install it with your package manager (e.g. 'apt install flatpak')."
check_cmd flatpak-builder \
    "Install it with 'apt install flatpak-builder' or 'flatpak install flatpak-builder'."

# Check that the required GNOME runtime is present
if ! flatpak info "org.gnome.Sdk//${GNOME_RUNTIME_VERSION}" &>/dev/null; then
    warn "org.gnome.Sdk//${GNOME_RUNTIME_VERSION} runtime not found.  Attempting to install from Flathub…"
    flatpak remote-add --user --if-not-exists flathub \
        https://flathub.org/repo/flathub.flatpakrepo || true
    flatpak install --user -y flathub \
        "org.gnome.Platform//${GNOME_RUNTIME_VERSION}" \
        "org.gnome.Sdk//${GNOME_RUNTIME_VERSION}" \
        || die "Could not install GNOME runtime.  Run manually:\n  flatpak install flathub org.gnome.Platform//${GNOME_RUNTIME_VERSION} org.gnome.Sdk//${GNOME_RUNTIME_VERSION}"
fi

# ── Clean ─────────────────────────────────────────────────────────────────────

if $CLEAN; then
    info "Cleaning previous build artifacts…"
    rm -rf "$BUILD_DIR" "$REPO_DIR"
    ok "Clean complete."
fi

mkdir -p "$OUTPUT_DIR"

# ── Build ─────────────────────────────────────────────────────────────────────

info "Building Flatpak: ${APP_ID}"
info "Manifest : ${MANIFEST}"
info "Build dir: ${BUILD_DIR}"
info "Repo dir : ${REPO_DIR}"

flatpak-builder \
    --user \
    --install-deps-from=flathub \
    --force-clean \
    --repo="$REPO_DIR" \
    "$BUILD_DIR" \
    "$MANIFEST"

ok "Build complete."

# ── Export bundle ─────────────────────────────────────────────────────────────

BUNDLE="${OUTPUT_DIR}/${APP_ID}.flatpak"
info "Exporting bundle → ${BUNDLE}"

flatpak build-bundle \
    "$REPO_DIR" \
    "$BUNDLE" \
    "$APP_ID"

BUNDLE_SIZE=$(du -sh "$BUNDLE" | cut -f1)
ok "Bundle created: ${BUNDLE}  (${BUNDLE_SIZE})"

# ── Install ───────────────────────────────────────────────────────────────────

if $INSTALL; then
    info "Installing ${APP_ID} for current user…"
    flatpak install --user --reinstall -y "$BUNDLE"
    ok "Installed."
fi

# ── Run ───────────────────────────────────────────────────────────────────────

if $RUN_APP; then
    info "Launching ${APP_ID}…"
    exec flatpak run "$APP_ID"
fi

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo -e "${GRN}╔══════════════════════════════════════════════════════╗${RST}"
echo -e "${GRN}║          Flatpak build finished successfully         ║${RST}"
echo -e "${GRN}╚══════════════════════════════════════════════════════╝${RST}"
echo ""
echo "  Bundle : ${BUNDLE}"
echo "  Size   : ${BUNDLE_SIZE}"
echo ""
echo "  To install:  flatpak install --user ${BUNDLE}"
echo "  To run:      flatpak run ${APP_ID}"
echo ""
