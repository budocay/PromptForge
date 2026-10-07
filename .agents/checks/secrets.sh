#!/bin/bash
# Usage : secrets.sh --index                  contenu indexé (pre-commit)
#         secrets.sh --plage <args git log>…  commits poussés ou d'une MR (pre-push, CI)
#         secrets.sh --arbre                  modifications non commitées + fichiers non suivis
# Sortie brute du scanner : affichée en cas d'échec, et toujours dans le rapport de controles.sh (preuve).
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
case "${1:-}" in
  --index) out="$(git diff --cached -U0 --no-color | outil SECRETS_STDIN 2>&1)" ;;
  --plage) shift                     # + ce que la résolution des merges ajoute à la fusion automatique
    out="$(outil SECRETS_PLAGE "$*" 2>&1)"; code=$?
    if [ $code -eq 0 ] && [ -n "$(git rev-list --merges "$@" 2>/dev/null)" ]; then
      out="$out$(for m in $(git rev-list --merges "$@"); do git show --remerge-diff --format= -U0 --no-color "$m"; done \
                 | outil SECRETS_STDIN 2>&1)"; code=$?
    fi
    (exit $code) ;;
  --arbre) out="$({ git diff HEAD -U0 --no-color
                    git ls-files -o --exclude-standard -z | xargs -0 cat 2>/dev/null; } | outil SECRETS_STDIN 2>&1)" ;;
  *) echec "usage : secrets.sh --index | --plage <args git log>… | --arbre" ;;
esac
code=$?
{ [ $code -ne 0 ] || [ -n "${SOCLE_TRACE:-}" ]; } && printf '%s\n' "$out" >&2
[ $code -eq 0 ] && exit 0
[ $code -eq 4 ] && exit 4
echec "secret détecté (scanner : code $code). Faux positif : allowlist du scanner, fichier protégé (§4.2)."
