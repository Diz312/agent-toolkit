#!/bin/bash
# Set up my whole agent toolkit on a Mac, end to end: Homebrew and tools, GitHub access, secrets,
# skills + MCP servers + plugins (skillshare-source), this repo with its git hook, and the Herdr
# skillshare panel when Herdr is installed. Install the AI apps you use first. Idempotent.
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/Diz312/agent-toolkit/main/bootstrap.sh)"
#
# Env: AGENT_TOOLKIT_DIR (default ~/myCode/agent-toolkit), APPLY_ARGS (extra apply.py flags).
set -euo pipefail

OWNER=Diz312
TOOLKIT_DIR="${AGENT_TOOLKIT_DIR:-$HOME/myCode/agent-toolkit}"
SECRETS="$HOME/.secrets/agent.env"
TTY="${BOOTSTRAP_TTY:-/dev/tty}"
HERDR_HOME="${HERDR_APP_HOME:-$HOME/.config/herdr-app}"
WARNINGS=()

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; WARNINGS+=("$*"); }
raw() { curl -fsSL "https://raw.githubusercontent.com/$OWNER/$1/main/$2"; }
have_tty() { [ -r "$TTY" ] && { [ "$TTY" != /dev/tty ] || : >/dev/tty; } 2>/dev/null; }
node_ok() {
  command -v node >/dev/null && node -e '
    const [a, b, c] = process.versions.node.split(".").map(Number);
    process.exit(a > 24 || (a === 24 && (b > 22 || (b === 22 && c >= 1))) ? 0 : 1)'
}

# --------------------------------------------------------------------------- 1. tools
step "Homebrew and tools"
if ! command -v brew >/dev/null; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" <"$TTY"
fi
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  if [ -x "$b" ]; then eval "$("$b" shellenv)"; break; fi
done
missing=()
for t in git gh skillshare uv; do command -v "$t" >/dev/null || missing+=("$t"); done
node_ok || missing+=(node)
if [ ${#missing[@]} -gt 0 ]; then brew install "${missing[@]}"; else echo "  all present"; fi
hash -r
node_ok || warn "node $(node -v 2>/dev/null) is older than 24.22.1 and comes first on PATH ($(command -v node)); the rea MCP server needs a newer one"

# --------------------------------------------------------------------------- 2. GitHub
step "GitHub sign-in (to push skill and catalog changes)"
if ! gh auth status >/dev/null 2>&1; then gh auth login --git-protocol https --web <"$TTY"; fi
gh auth setup-git
echo "  signed in as $(gh api user -q .login)"

# --------------------------------------------------------------------------- 3. secrets
step "Secrets (~/.secrets/agent.env)"
mkdir -p "$(dirname "$SECRETS")" && chmod 700 "$(dirname "$SECRETS")"
touch "$SECRETS" && chmod 600 "$SECRETS"
example=$(raw agent-toolkit .env.example)
hint=""
while IFS= read -r line; do
  case "$line" in
    "") hint="" ;;
    \#*) hint="${line#\# }" ;;
    *=*)
      key="${line%%=*}"
      if grep -q "^${key}=." "$SECRETS"; then echo "  $key: set"; continue; fi
      if ! have_tty; then warn "$key is not set; add it to $SECRETS and re-run"; continue; fi
      [ -n "$hint" ] && printf '  %s\n' "$hint" >&2
      printf '  %s (Enter to skip): ' "$key" >&2
      stty -echo <"$TTY" 2>/dev/null || true
      IFS= read -r value <"$TTY" || value=""
      stty echo <"$TTY" 2>/dev/null || true
      echo >&2
      if [ -n "$value" ]; then
        grep -v "^${key}=" "$SECRETS" >"$SECRETS.tmp" || true
        printf '%s=%s\n' "$key" "$value" >>"$SECRETS.tmp" && mv "$SECRETS.tmp" "$SECRETS"
        chmod 600 "$SECRETS"
        echo "  $key: saved"
      else
        warn "$key skipped; servers that need it will fail until you add it and re-run"
      fi ;;
  esac
done <<<"$example"

# --------------------------------------------------------------------------- 4. skillshare
step "Skills, MCP servers and plugins (skillshare-source)"
raw skillshare-source bootstrap.sh | sh

# --------------------------------------------------------------------------- 5. this repo
step "agent-toolkit ($TOOLKIT_DIR)"
if [ -d "$TOOLKIT_DIR/.git" ]; then
  git -C "$TOOLKIT_DIR" pull --ff-only -q || warn "could not fast-forward $TOOLKIT_DIR; pull it by hand"
else
  mkdir -p "$(dirname "$TOOLKIT_DIR")"
  git clone -q "https://github.com/$OWNER/agent-toolkit.git" "$TOOLKIT_DIR"
fi
# shellcheck disable=SC2086
(cd "$TOOLKIT_DIR" && uv run -q --script scripts/apply.py --install-hook ${APPLY_ARGS:-}) \
  || warn "apply.py reported problems (output above)"

# --------------------------------------------------------------------------- 6. Herdr panel
step "Herdr skillshare panel"
if command -v herdr-app >/dev/null && [ -d "$HERDR_HOME" ]; then
  if [ ! -d "$HERDR_HOME/mods/skillshare" ]; then
    tmp=$(mktemp -d)
    git clone -q --depth 1 --filter=blob:none --sparse https://github.com/runkids/skillshare.git "$tmp/r"
    git -C "$tmp/r" sparse-checkout set herdr/skillshare
    src="$tmp/r/herdr/skillshare"
    mkdir -p "$HERDR_HOME/layouts" "$HERDR_HOME/mods"
    cp -n "$src/layouts/herdr-skillshare.json" "$src/layouts/herdr-skillshare.png" "$HERDR_HOME/layouts/"
    cp -R "$src/mods/skillshare" "$HERDR_HOME/mods/skillshare"
    rm -rf "$tmp"
  fi
  herdr-app check "$HERDR_HOME/mods/skillshare" || warn "the Herdr panel failed its check"
  herdr-app do layout.switch --name herdr-skillshare >/dev/null 2>&1 \
    || warn "open Herdr and switch to the skillshare layout (ctrl-shift-l)"
else
  echo "  Herdr not installed; skipped"
fi

# --------------------------------------------------------------------------- 7. check
step "Check"
set -a; . "$SECRETS"; set +a
skillshare doctor </dev/null 2>&1 | grep -E "Source|Integrity|MCP |Plugins|✗ [0-9]" || true
if command -v claude >/dev/null; then
  claude mcp list 2>/dev/null | grep -E "^(context7|gitnexus|playwright|rea):" || true
fi

printf '\n\033[1mDone.\033[0m Quit and reopen Claude Code (desktop and terminal) and Cursor.\n'
echo "Run the daily scout from one machine only: in the Claude desktop app, a scheduled task in"
echo "$TOOLKIT_DIR with the prompt \"Run the toolkit scout\"."
if [ ${#WARNINGS[@]} -gt 0 ]; then
  echo; echo "Needs you:"; printf '  - %s\n' "${WARNINGS[@]}"
fi
