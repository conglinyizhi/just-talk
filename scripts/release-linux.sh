#!/usr/bin/env bash
set -euo pipefail

build=1
if [ "${1:-}" = "--no-build" ]; then
  build=0
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

version="$(python - <<'PY'
import tomllib
from pathlib import Path

data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
print(data["project"]["version"])
PY
)"

binary="dist/just-talk-x86_64"
if [ $build -eq 1 ] && [ ! -x "$binary" ]; then
  if command -v make >/dev/null 2>&1; then
    make build-linux
  else
    echo "make not found; run pyinstaller manually first" >&2
    exit 1
  fi
fi

if [ ! -x "$binary" ]; then
  echo "Binary not found at $binary" >&2
  exit 1
fi

release_dir="release"
pkg="just-talk-linux-x86_64-v${version}.tar.zst"
mkdir -p "$release_dir"

if ! command -v zstd >/dev/null 2>&1; then
  echo "zstd not found; install zstd to build the release archive" >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
cp "$binary" "$tmpdir/just-talk"
cp icon.png just-talk.desktop LICENSE "$tmpdir/"
tar -cf - -C "$tmpdir" just-talk icon.png just-talk.desktop LICENSE | zstd -19 -T0 -f -o "${release_dir}/${pkg}"
rm -rf "$tmpdir"

sha256="$(sha256sum "${release_dir}/${pkg}" | awk '{print $1}')"

if [ -f "aur/PKGBUILD" ]; then
  python - <<PY
from pathlib import Path
import re

version = "${version}"
sha256 = "${sha256}"
path = Path("aur/PKGBUILD")
text = path.read_text(encoding="utf-8")
text = re.sub(r"^pkgver=.*$", f"pkgver={version}", text, flags=re.M)
text = re.sub(r"^sha256sums=\\('[0-9a-f]+'\\)$", f"sha256sums=('{sha256}')", text, flags=re.M)
path.write_text(text, encoding="utf-8")
PY
fi

if [ -f "aur/.SRCINFO" ]; then
  python - <<PY
from pathlib import Path
import re

version = "${version}"
sha256 = "${sha256}"
path = Path("aur/.SRCINFO")
text = path.read_text(encoding="utf-8")
text = re.sub(r"^\\tpkgver = .*$", f"\\tpkgver = {version}", text, flags=re.M)
text = re.sub(r"just-talk-linux-x86_64-v[0-9.]+\\.tar\\.zst", f"just-talk-linux-x86_64-v{version}.tar.zst", text)
text = re.sub(r"^\\tsha256sums = [0-9a-f]+$", f"\\tsha256sums = {sha256}", text, flags=re.M)
path.write_text(text, encoding="utf-8")
PY
fi

echo "${release_dir}/${pkg}"
