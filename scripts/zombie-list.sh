#!/bin/bash
# zombie-parents.sh
# List unique parent processes that have zombie children, with zombie counts.

set -euo pipefail

echo "🔎 Searching for parent processes with zombie children..."

# Get all zombies with their parent PID
ps -eo ppid,state | awk '$2=="Z"{print $1}' | sort -n | uniq -c | while read -r COUNT PARENT; do
    # Get the parent command name
    PNAME=$(ps -p "$PARENT" -o comm= 2>/dev/null || echo "[exited]")
    echo "Parent PID=$PARENT, Command=$PNAME, Zombie count=$COUNT"
done
