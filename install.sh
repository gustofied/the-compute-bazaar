#!/bin/sh

set -eu

REPO_URL="${COMPUTE_BAZAAR_REPO_URL:-https://github.com/gustofied/the-compute-bazaar.git}"
INSTALL_DIR="${COMPUTE_BAZAAR_INSTALL_DIR:-$HOME/.local/share/compute-bazaar}"
BIN_DIR="${COMPUTE_BAZAAR_BIN_DIR:-$HOME/.local/bin}"

fail() {
    printf 'compute-bazaar: %s\n' "$1" >&2
    exit 1
}

command -v git >/dev/null 2>&1 || fail "git is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"

if ! command -v uv >/dev/null 2>&1; then
    printf 'Installing uv...\n'
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    export PATH
fi
command -v uv >/dev/null 2>&1 || fail "uv was installed, but is not on PATH"

if [ -d "$INSTALL_DIR/.git" ]; then
    printf 'Updating %s...\n' "$INSTALL_DIR"
    git -C "$INSTALL_DIR" pull --ff-only
elif [ -e "$INSTALL_DIR" ]; then
    fail "$INSTALL_DIR exists and is not a Compute Bazaar checkout"
else
    printf 'Cloning The Compute Bazaar...\n'
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

printf 'Installing the CLI and Terminal...\n'
uv sync --project "$INSTALL_DIR" --extra terminal --no-dev

if command -v node >/dev/null 2>&1 \
    && command -v pnpm >/dev/null 2>&1 \
    && command -v cargo >/dev/null 2>&1; then
    pnpm --dir "$INSTALL_DIR/terminal" install --frozen-lockfile
    terminal_mode="native"
else
    terminal_mode="browser"
fi

printf 'Syncing the public market lake...\n'
"$INSTALL_DIR/.venv/bin/compute-bazaar" data sync

mkdir -p "$BIN_DIR"
ln -sf "$INSTALL_DIR/.venv/bin/compute-bazaar" "$BIN_DIR/compute-bazaar"

printf '\nInstalled in %s\n' "$INSTALL_DIR"
printf 'Terminal mode: %s\n' "$terminal_mode"
if [ "$terminal_mode" = "browser" ]; then
    printf 'Install Node.js, pnpm, and Rust to enable the native window.\n'
fi
if ! command -v compute-bazaar >/dev/null 2>&1; then
    printf 'Add %s to PATH, then run:\n' "$BIN_DIR"
else
    printf 'Run:\n'
fi
printf '  compute-bazaar terminal\n'
