#!/bin/sh

set -eu

REPO_URL="${COMPUTE_BAZAAR_REPO_URL:-https://github.com/gustofied/the-compute-bazaar.git}"
BIN_DIR="${COMPUTE_BAZAAR_BIN_DIR:-$HOME/.local/bin}"
OPEN_TERMINAL=0
SOURCE_INSTALL=0

fail() {
    printf 'compute-bazaar: %s\n' "$1" >&2
    exit 1
}

if [ "${1:-}" = "--open" ]; then
    OPEN_TERMINAL=1
    shift
fi
[ "$#" -eq 0 ] || fail "usage: install.sh [--open]"

if [ -n "${COMPUTE_BAZAAR_INSTALL_DIR:-}" ]; then
    INSTALL_DIR="$COMPUTE_BAZAAR_INSTALL_DIR"
elif [ "${0##*/}" = "install.sh" ]; then
    script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
    if [ -e "$script_dir/.git" ] \
        && [ -f "$script_dir/pyproject.toml" ] \
        && [ -f "$script_dir/terminal/package.json" ]; then
        INSTALL_DIR="$script_dir"
        SOURCE_INSTALL=1
    else
        INSTALL_DIR="$HOME/.local/share/compute-bazaar/app"
    fi
else
    INSTALL_DIR="$HOME/.local/share/compute-bazaar/app"
fi

command -v git >/dev/null 2>&1 || fail "git is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"

if ! command -v uv >/dev/null 2>&1; then
    printf 'Installing uv...\n'
    mkdir -p "$BIN_DIR"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$BIN_DIR" sh
    PATH="$BIN_DIR:$HOME/.cargo/bin:$PATH"
    export PATH
fi
command -v uv >/dev/null 2>&1 || fail "uv was installed, but is not on PATH"

if [ "$SOURCE_INSTALL" -eq 1 ]; then
    printf 'Using %s...\n' "$INSTALL_DIR"
elif [ -d "$INSTALL_DIR/.git" ]; then
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
if [ "$SOURCE_INSTALL" -eq 1 ]; then
    uv sync --project "$INSTALL_DIR" --frozen
else
    uv sync --project "$INSTALL_DIR" --frozen --no-dev
fi

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
case ":${PATH:-}:" in
    *":$BIN_DIR:"*) ;;
    *)
        if [ "$(uv tool dir --bin 2>/dev/null || true)" = "$BIN_DIR" ] \
            && uv tool update-shell >/dev/null 2>&1; then
            printf 'Added %s to your shell PATH.\n' "$BIN_DIR"
        else
            printf 'Add %s to your shell PATH.\n' "$BIN_DIR"
        fi
        ;;
esac

if [ "$OPEN_TERMINAL" -eq 1 ]; then
    printf 'Opening the Terminal...\n'
    "$INSTALL_DIR/.venv/bin/compute-bazaar" terminal
else
    printf 'Run:\n'
    printf '  compute-bazaar terminal\n'
fi
