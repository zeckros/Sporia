#!/usr/bin/env bash
# Génère web/css/tailwind.css via la CLI Tailwind standalone (aucun Node requis).
set -euo pipefail
CLI="tools/tailwindcss"
VER="v3.4.17"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) BIN="tailwindcss-windows-x64.exe"; CLI="tools/tailwindcss.exe";;
  Darwin) BIN="tailwindcss-macos-x64";;
  *) BIN="tailwindcss-linux-x64";;
esac
mkdir -p tools web/css
if [ ! -f "$CLI" ]; then
  echo "Téléchargement Tailwind CLI $VER ($BIN)…"
  curl -sL "https://github.com/tailwindlabs/tailwindcss/releases/download/${VER}/${BIN}" -o "$CLI"
  chmod +x "$CLI"
fi
"$CLI" -c tailwind.config.js -i web/css/tailwind.input.css -o web/css/tailwind.css --minify
echo "OK → web/css/tailwind.css"
