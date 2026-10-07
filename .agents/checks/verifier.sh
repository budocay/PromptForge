#!/bin/bash
# Usage : verifier.sh [--cle K] [--ref SHA]
# Tests (chaque chaîne d'outils) + secrets non commités, plafond de 3 échecs consécutifs par clé (§5.6).
# --ref : teste exactement le commit SHA (pre-push, CI) ; si l'arbre n'est pas propre ou que SHA n'est
#         pas HEAD, le test se fait dans un worktree temporaire (TEST_SETUP_CMD y installe les dépendances).
# Un UNVERIFIED accepté par le dev (ACCEPTE_UNVERIFIED, ou ACCEPTE_UNVERIFIED_LOCAL hors CI) ne bloque pas.
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
cle=defaut; ref=""
while [ $# -gt 0 ]; do
  case "$1" in --cle) cle="$2"; shift 2 ;; --ref) ref="$2"; shift 2 ;; *) echec "argument inconnu : $1" ;; esac
done
mkdir -p .agents/.state; compteur=".agents/.state/verifier-$(printf '%s' "$cle" | tr -c 'A-Za-z0-9_-' '_').count"

dir="$RACINE"
if [ -n "$ref" ] && { [ -n "$(git status --porcelain)" ] || [ "$(git rev-parse "$ref")" != "$(git rev-parse HEAD)" ]; }; then
  dir="$(mktemp -d)"
  trap 'git worktree remove --force "$dir" >/dev/null 2>&1; rm -rf "$dir"' EXIT
  git worktree add --detach --quiet "$dir" "$ref" || echec "impossible d'extraire $ref"
fi

code=0; out=""
noter() { # noter <contrôle> <code> <sortie>
  out="$out$3"$'\n'
  case $2 in
    0) ;;
    4) if accepte "$1"; then out="$out$1 : UNVERIFIED accepté par le dev (dette)"$'\n'
       else [ $code -eq 0 ] && code=4; fi ;;
    *) code=2 ;;
  esac
}
for t in $(chaines); do
  p="$(prefixe "$t")"; r=.; setup=""; eval "r=\${${p}TEST_RACINE:-.}; setup=\${${p}TEST_SETUP_CMD:-}"
  o="$( (cd "$dir/$r" || echec "${p}TEST_RACINE introuvable : $r"
         if [ "$dir" != "$RACINE" ] && [ -n "$setup" ]; then outil "${p}TEST_SETUP" >/dev/null || exit $?; fi
         outil "${p}TEST") 2>&1)"; c=$?
  noter "tests$(suffixe "$t")" "$c" "$o"
done
o="$( (cd "$dir" && "$RACINE/.agents/checks/secrets.sh" --arbre) 2>&1)"; c=$?; noter secrets "$c" "$o"

if [ $code -eq 0 ]; then rm -f "$compteur"; [ -z "${out//[[:space:]]/}" ] || printf '%s' "$out" | grep 'accepté' >&2; exit 0; fi
n=$(( $(cat "$compteur" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$compteur"
printf '%s\n' "$out" | tail -c 3000 >&2                 # extrait de sortie brute = preuve (§3.0)
if [ "$n" -ge 3 ]; then rm -f "$compteur"; echo "ESCALADE (§5.6) : 3 échecs consécutifs." >&2; exit 3; fi
exit $code
