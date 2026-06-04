#!/bin/bash
# Watches prototype.html for changes and re-runs extraction automatically.
# Usage: ./watch_prototype.sh <prototype.html> [output-dir]

PROTO="${1:-prototype.html}"
OUTDIR="${2:-agent-context}"

if [ ! -f "$PROTO" ]; then
  echo "Error: $PROTO not found"
  exit 1
fi

echo "Watching $PROTO for changes... (Ctrl+C to stop)"

run_extraction() {
  echo "\n[$(date '+%H:%M:%S')] Change detected — re-extracting..."
  python3 "$(dirname "$0")/extract_design_system.py" "$PROTO" "$OUTDIR"
}

# Run once immediately
run_extraction

# Watch for changes (requires fswatch on macOS: brew install fswatch)
if command -v fswatch &>/dev/null; then
  fswatch -o "$PROTO" | while read; do run_extraction; done
else
  echo "\nfswatch not found. Install it to enable auto-watch:"
  echo "  brew install fswatch"
  echo "\nFor now, re-run manually:"
  echo "  python3 extract_design_system.py $PROTO $OUTDIR"
fi
