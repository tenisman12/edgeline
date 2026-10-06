#!/usr/bin/env bash
# utilidades/subir_a_main.sh "<mensaje>" archivo1 archivo2 ...
# Sube a main SOLO los archivos que existen, resuelve choques a favor de la version recien generada
# y reintenta si el push pierde la carrera. Los archivos modificados que NO van en la lista se apartan
# (git stash) antes de traer main, para que el rebase no falle por "unstaged changes".
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
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Archivos modificados que no van en esta subida (se apartan):"
  git status --short --untracked-files=no | head -20
  git stash push -q -m "apartado por subir_a_main" || git checkout -q -- .
fi
for intento in 1 2 3; do
  git pull -q --rebase -X theirs origin main || { git rebase --abort 2>/dev/null; echo "rebase fallo (intento $intento)"; git status --short | head -10; sleep 5; continue; }
  if git push -q origin HEAD:main; then echo "Subido: $lista"; exit 0; fi
  echo "push fallo (intento $intento)"; sleep 5
done
echo "::error::No se pudo subir a main"; exit 1