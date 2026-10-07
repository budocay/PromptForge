#!/bin/bash
# Usage : lecture-seule.sh debut <clé> | fin <clé>
# Empreinte de l'arbre de travail avant/après un gate. « fin » échoue si le gate a modifié quoi que ce
# soit (fichiers suivis ou non suivis, hors fichiers ignorés et hors MEMORY/gates.log, que les gates
# parallèles alimentent). Garantie indépendante du harness.
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
empreinte() {
  { git status --porcelain=v1 -uall -- . ':!MEMORY/gates.log'; git diff HEAD --binary -- . ':!MEMORY/gates.log'
    git ls-files -o --exclude-standard -z -- . ':!MEMORY/gates.log' | xargs -0 cat 2>/dev/null; } | git hash-object --stdin
}
mkdir -p .agents/.state; f=".agents/.state/ro-$(printf '%s' "${2:?clé}" | tr -c 'A-Za-z0-9_-' '_')"
case "${1:-}" in
  debut) empreinte > "$f" ;;
  fin)   [ -f "$f" ] || non_verifie "pas d'empreinte de début pour '$2'"
         [ "$(empreinte)" = "$(cat "$f")" ] || { git status --short >&2; rm -f "$f"; echec "le gate '$2' a modifié l'arbre : verdict invalide"; }
         rm -f "$f" ;;
  *) echec "usage : lecture-seule.sh debut|fin <clé>" ;;
esac
