#!/usr/bin/env bash
# Run on the Synology once the app is installed: one full nightly run while the memory of every container is
# sampled. Reports the time per job, the total (must stay under 60 minutes) and the peak memory per container
# against the memory of the NAS.
#   scripts/nas-check.sh
set -uo pipefail
cd "$(dirname "$0")/.."
compose="docker compose ${COMPOSE_FILES:-}"
log=$(mktemp); stats=$(mktemp)

echo "Geheugen van de NAS:"; free -m | sed -n '1,2p'
echo "Processor: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2)"
echo
echo "Volledige nachtrun starten (dit duurt even)..."
( while true; do docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' >> "$stats"; sleep 10; done ) &
sampler=$!
start=$(date +%s)
$compose exec -T server python -m app.cli nightly > "$log" 2>&1
code=$?
end=$(date +%s)
kill $sampler 2>/dev/null

echo
grep -A20 '"jobs_seconds"' "$log" | sed -n '1,20p'
minutes=$(( (end - start + 59) / 60 ))
echo
echo "Totaal: ${minutes} minuten (eis: binnen 60)."
echo
echo "Hoogste geheugengebruik per container:"
awk '{ name=$1; v=$2; unit=v; gsub(/[0-9.]/,"",unit); gsub(/[A-Za-z]/,"",v);
       mb = (unit=="GiB") ? v*1024 : (unit=="KiB" ? v/1024 : v);
       if (mb > max[name]) max[name]=mb }
     END { for (n in max) printf "  %-28s %6.0f MB\n", n, max[n] }' "$stats" | sort
rm -f "$log" "$stats"
if [ $code -ne 0 ]; then echo "Let op: een of meer taken eindigden met fouten (zie Instellingen en verbruik)."; fi
if [ $minutes -gt 60 ]; then echo "TE LANGZAAM: de nachtrun duurt langer dan een uur."; exit 1; fi
echo "OK"
