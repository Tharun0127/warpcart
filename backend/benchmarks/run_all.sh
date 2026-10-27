#!/bin/sh
# Runs the cache-off and cache-on load tests back to back.
# Run from the HOST in the project root:   sh backend/benchmarks/run_all.sh
# Locust and the API share the same CPUs, so we use ONE Locust process:
# extra Locust processes steal CPU from the API and lower its throughput.
# Each run restarts the API with a different CACHE_ENABLED value, so both
# runs use the same build, data and hardware.
set -e

USERS=${USERS:-50}
DURATION=${DURATION:-60s}

wait_for_api() {
  until docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" 2>/dev/null; do
    sleep 2
  done
}

run() {
  label=$1; enabled=$2; prefix=$3
  echo "== $label (CACHE_ENABLED=$enabled)"
  CACHE_ENABLED=$enabled docker compose up -d api
  wait_for_api
  docker compose exec -T redis redis-cli FLUSHDB >/dev/null   # start cold, every run
  docker compose exec -T api python -m benchmarks.summarize --reset
  docker compose exec -T api locust -f benchmarks/locustfile.py --headless -u "$USERS" -r 50 -t "$DURATION" \
    --host http://localhost:8000 --csv "benchmarks/results/$prefix" --only-summary >/dev/null 2>&1
  docker compose exec -T api python -m benchmarks.summarize "benchmarks/results/$prefix" "$label"
  # The container is recreated for the next run, so copy the CSV out now.
  docker compose cp "api:/app/benchmarks/results/${prefix}_stats.csv" backend/benchmarks/results/ >/dev/null
}

run "cache off" false cache_off
run "cache on" true cache_on

echo "== stampede (lock)"
docker compose exec -T api python -m benchmarks.stampede
