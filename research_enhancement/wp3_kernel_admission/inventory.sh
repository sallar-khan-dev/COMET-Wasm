#!/usr/bin/env bash
set -u

echo "=== EXISTING WP3 SCRIPTS ==="
find experiments research_enhancement -type f \
  \( -iname '*kernel*' -o -iname '*admission*' \
  -o -iname '*cold_start*' -o -iname '*execution_time*' \) \
  2>/dev/null | sort

echo
echo "=== EXISTING WP3 RESULTS ==="
find results/raw -type f \
  \( -iname '*kernel*' -o -iname '*admission*' \
  -o -iname '*cold_start*' -o -iname '*execution_time*' \) \
  2>/dev/null | sort

echo
echo "=== MODEL AND SERVICE ENTRYPOINTS ==="
find . -maxdepth 5 -type f \
  \( -name 'Cargo.toml' -o -name 'Dockerfile*' \
  -o -name 'server.py' -o -name 'main.rs' \
  -o -name 'run_execution_time_full.py' \
  -o -name 'run_cold_start_full.py' \) \
  -not -path './.git/*' 2>/dev/null | sort | head -100

echo
echo "=== SERVER STATUS ==="
uptime
free -h
