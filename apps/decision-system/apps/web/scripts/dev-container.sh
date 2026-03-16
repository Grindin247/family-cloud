#!/bin/sh
set -eu

# Keep dev artifacts clean between container starts.
find .next -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true

npm run dev &
NEXT_PID=$!

cleanup() {
  kill "$NEXT_PID" 2>/dev/null || true
}

trap cleanup INT TERM

# Next.js occasionally requires server chunks from /server/*.js.
# Mirror chunk files from /server/chunks so runtime chunk imports resolve.
while kill -0 "$NEXT_PID" 2>/dev/null; do
  if [ -d ".next/server/chunks" ] && [ -d ".next/server" ]; then
    for file in .next/server/chunks/*.js; do
      [ -e "$file" ] || break
      name=$(basename "$file")
      if [ ! -e ".next/server/$name" ]; then
        cp -f "$file" ".next/server/$name" 2>/dev/null || true
      fi
    done
  fi
  sleep 1
done

wait "$NEXT_PID"

