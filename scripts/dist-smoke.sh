#!/bin/sh
# Clean-install smoke (validation §6.1, cleanup-map §1): build the wheel, install it into a
# fresh venv, and run it from outside the checkout. `import delivery` must fail (D46).
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

uv build --quiet --wheel --out-dir "$work/dist" "$root"
uv venv --quiet --python 3.12 "$work/venv"
uv pip install --quiet --python "$work/venv/bin/python" "$work"/dist/*.whl

cd "$work"
"$work/venv/bin/loopctl" --help >/dev/null
"$work/venv/bin/python" -c "import loopctl.tools"
if "$work/venv/bin/python" -c "import delivery" 2>/dev/null; then
  echo "dist-smoke: FAIL: import delivery succeeded" >&2
  exit 1
fi
echo "dist-smoke: ok"
