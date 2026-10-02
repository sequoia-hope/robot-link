#!/usr/bin/env bash
# launch.sh — launch claude in a tmux session in this directory.
# Reconnects if the session already exists. Use -r to force restart.
set -euo pipefail

SESSION="comms"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_CMD="claude --dangerously-skip-permissions"
FORCE_RESTART=false

while getopts "r" opt; do
  case "$opt" in
    r) FORCE_RESTART=true ;;
    *) echo "Usage: $0 [-r]  ( -r = force restart session )"; exit 1 ;;
  esac
done

# `=` means an exact session name. A bare target is a *prefix* match, and this
# machine has sibling projects whose names start with each other's (finance and
# finance-llm, conversational_agent and conversational_agent-stt). Unanchored,
# `finance/launch.sh` finds "finance-llm" when its own session is not running,
# attaches you to that project's agent, and with -r kills it.
if $FORCE_RESTART && tmux has-session -t "=$SESSION" 2>/dev/null; then
  tmux kill-session -t "=$SESSION"
fi

# Create session if it doesn't exist. `exec bash` keeps the pane alive if claude exits.
if ! tmux has-session -t "=$SESSION" 2>/dev/null; then
  tmux new-session -d -s "$SESSION" -c "$DIR" "$CLAUDE_CMD; exec bash"
  echo "Created tmux session '$SESSION' in $DIR"
fi

# Attach
exec tmux attach-session -t "=$SESSION"
