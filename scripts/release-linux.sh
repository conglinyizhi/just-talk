#!/usr/bin/env bash
set -euo pipefail

# 此脚本用于更新 AUR 的 PKGBUILD 和 .SRCINFO 文件
# 使用 GitHub Release 上的 AppImage 文件

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

version="$(python - <<'PY'
import tomllib
from pathlib import Path

data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
print(data["project"]["version"])
PY
)"

# AppImage 文件名格式
appimage="just-talk-${version}-x86_64.AppImage"
release_url="https://github.com/whoamihappyhacking/just-talk/releases/download/v${version}/${appimage}"

# 下载 AppImage 并计算 sha256
echo "Downloading ${appimage} to calculate sha256..."
tmpfile="$(mktemp)"
if ! curl -fsSL -o "$tmpfile" "$release_url"; then
  echo "Failed to download ${release_url}" >&2
  echo "Make sure v${version} release exists with the AppImage file" >&2
  rm -f "$tmpfile"
  exit 1
fi

sha256="$(sha256sum "$tmpfile" | awk '{print $1}')"
rm -f "$tmpfile"

echo "Version: ${version}"
echo "SHA256: ${sha256}"

aur_dir="${repo_root}/../just-talk-aur"

if [ -f "${aur_dir}/PKGBUILD" ]; then
  echo "Updating ${aur_dir}/PKGBUILD..."
  python - <<PY
from pathlib import Path
import re

version = "${version}"
sha256 = "${sha256}"
path = Path("${aur_dir}/PKGBUILD")
text = path.read_text(encoding="utf-8")
text = re.sub(r"^pkgver=.*$", f"pkgver={version}", text, flags=re.M)
text = re.sub(r"^sha256sums=\('[0-9a-f]+'\)$", f"sha256sums=('{sha256}')", text, flags=re.M)
path.write_text(text, encoding="utf-8")
PY
  echo "Updated PKGBUILD"
fi

if [ -f "${aur_dir}/.SRCINFO" ]; then
  echo "Updating ${aur_dir}/.SRCINFO..."
  python - <<PY
from pathlib import Path
import re

version = "${version}"
sha256 = "${sha256}"
path = Path("${aur_dir}/.SRCINFO")
text = path.read_text(encoding="utf-8")
text = re.sub(r"^\tpkgver = .*$", f"\tpkgver = {version}", text, flags=re.M)
text = re.sub(r"just-talk-[0-9.]+-x86_64\.AppImage", f"just-talk-{version}-x86_64.AppImage", text)
text = re.sub(r"^\tsha256sums = [0-9a-f]+$", f"\tsha256sums = {sha256}", text, flags=re.M)
path.write_text(text, encoding="utf-8")
PY
  echo "Updated .SRCINFO"
fi

echo "Done! AUR files updated to v${version}"
