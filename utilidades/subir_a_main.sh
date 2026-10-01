#!/usr/bin/env bash
# utilidades/subir_a_main.sh "<mensaje>" archivo1 archivo2 ...
# Sube a main SOLO los archivos que existen (git add -f falla si falta uno), resuelve choques con tus pushes
# a favor de la version recien generada y reintenta una vez si el push pierde la carrera.
set -u
msg="$1"; shift
git config user.name "edgeline-bot"
git config user.email "edgeline-bot@users.noreply.github.com"
lista=""
for f in "$@"; do
  for g in $f; do [ -f "$g" ] && lista="$lista $g"; done
done
if [ -z "$lista" ]; then echo "Nada que subir."; exit 0; fi
git add -f $lista
if git diff --cached --quiet; then echo "Sin cambios."; exit 0; fi
git commit -q -m "$msg $(date -u +'%Y-%m-%d %H:%M')Z"
for intento in 1 2 3; do
  git pull -q --rebase -X theirs origin main || { git rebase --abort 2>/dev/null; echo "rebase fallo (intento $intento)"; sleep 5; continue; }
  if git push -q origin HEAD:main; then echo "Subido: $lista"; exit 0; fi
  echo "push fallo (intento $intento)"; sleep 5
done
echo "::error::No se pudo subir a main"; exit 1
