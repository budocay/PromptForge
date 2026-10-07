#!/bin/bash
# Usage : format-lint.sh --index | <fichier>… | (sans argument : fichiers modifiés depuis HEAD)
# Formateur puis linter de chaque chaîne d'outils, sur ses extensions (FORMAT_EXT, LINT_EXT ou, avec
# TOOLCHAINS, <TC>_FORMAT_EXT, <TC>_LINT_EXT).
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
liste=()
ajouter() { while IFS= read -r f; do [ -n "$f" ] && liste+=("$f"); done; }
if [ "${1:-}" = --index ]; then ajouter <<EOF2
$(git diff --cached --name-only --diff-filter=ACMR)
EOF2
elif [ $# -gt 0 ]; then liste=("$@")
else ajouter <<EOF2
$(git diff HEAD --name-only --diff-filter=ACMR; git ls-files -o --exclude-standard)
EOF2
fi
[ ${#liste[@]} -gt 0 ] || exit 0
# Fichiers du socle, projections, lockfiles et code généré ne sont pas du code écrit par les agents.
exclus="${FORMAT_LINT_EXCLUDE-.agents/* .githooks/* .claude/* .cursor/* .codex/* AGENTS.md CLAUDE.md CODEOWNERS MEMORY/gates.log *.lock *-lock.yaml *-lock.json *.lockb *.g.dart *.freezed.dart}"
gardes=(); set -f                                  # les motifs ne doivent pas s'étendre sur le disque
for f in "${liste[@]}"; do
  garder=1
  for g in $exclus; do
    # shellcheck disable=SC2053  # correspondance de glob voulue
    [[ "$f" == $g ]] && { garder=0; break; }
  done
  [ $garder -eq 1 ] && gardes+=("$f")
done; set +f
[ ${#gardes[@]} -gt 0 ] || exit 0
liste=("${gardes[@]}")

lancer() { # lancer NOM EXTS : outil NOM sur les fichiers filtrés
  local sel=() f
  while IFS= read -r f; do [ -n "$f" ] && sel+=("$f"); done <<EOF2
$(filtre_ext "$2" "${liste[@]}")
EOF2
  [ ${#sel[@]} -gt 0 ] || return 0
  ( outil "$1" "${sel[@]}" )
}
rc=0
for t in $(chaines); do
  p="$(prefixe "$t")"; eval "fe=\${${p}FORMAT_EXT:-}; le=\${${p}LINT_EXT:-}"
  if [ "$t" != - ] && { [ -z "$fe" ] || [ -z "$le" ]; }; then echec "${p}FORMAT_EXT et ${p}LINT_EXT obligatoires avec TOOLCHAINS"; fi
  for etape in "FORMAT_CHECK:$fe:formatage non conforme" "LINT:$le:linter en erreur"; do
    IFS=: read -r nom exts msg <<EOF2
$etape
EOF2
    lancer "$p$nom" "$exts"; c=$?
    case $c in
      0) ;;
      4) if accepte "format-lint$(suffixe "$t")"; then echo "UNVERIFIED accepté par le dev : $p$nom" >&2
         else [ $rc -eq 0 ] && rc=4; fi ;;
      *) echo "FAIL : $msg ($p$nom)" >&2; rc=2 ;;
    esac
  done
done
exit $rc
