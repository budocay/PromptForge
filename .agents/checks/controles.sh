#!/bin/bash
# Usage : controles.sh [--conception] <base> | --tout
# Tous les contrôles déterministes sur <base>..HEAD (--tout : tout l'historique, premier push). Point
# d'entrée unique de la CI (quelle que soit la plateforme) et de dossier-revue.sh. Imprime un rapport
# (preuve §3.0 : commande exacte et sortie brute de chaque outil) ; codes : 0 · 2 · 4.
# --conception : revue d'une conception sans code (pipeline STRUCTUREL, §6.1) : pas de ac-couverture.
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
conception=0; [ "${1:-}" = --conception ] && { conception=1; shift; }
base="${1:?usage : controles.sh [--conception] <base> | --tout}"
if [ "$base" = --tout ]; then plage=HEAD; base_deps="$(git hash-object -t tree /dev/null)"   # arbre vide
else
  git rev-parse --verify --quiet "$base^{commit}" >/dev/null \
    || echec "base introuvable : $base (en CI, récupérer l'historique complet : profondeur de clone illimitée)"
  plage="$base..HEAD"; base_deps="$base"
fi
C=.agents/checks; global=0; export SOCLE_TRACE=1

etape() { # etape <nom> <commande…>
  local nom="$1" out code s; shift
  out="$("$@" 2>&1)"; code=$?
  case $code in
    0) s=OK ;;
    4) if accepte "$nom"; then s="UNVERIFIED (accepté par le dev)"; else s=UNVERIFIED; [ $global -eq 0 ] && global=4; fi ;;
    *) s="FAIL (code $code)"; global=2 ;;
  esac
  echo "CONTROLE $nom: $s"
  [ -n "$out" ] && printf '%s\n' "$out" | tail -c 2000 | sed 's/^/    /'
  return 0
}

modifies=()
while IFS= read -r f; do [ -n "$f" ] && [ -f "$f" ] && modifies+=("$f"); done <<EOF2
$({ git log --no-merges --format= --name-only "$plage"
   for m in $(git rev-list --merges "$plage"); do git show --remerge-diff --format= --name-only "$m"; done; } | sort -u)
EOF2

etape perimetre    "$C/perimetre.sh" --commits "$plage"
etape secrets      "$C/secrets.sh" --plage "$plage"
[ ${#modifies[@]} -gt 0 ] && etape format-lint "$C/format-lint.sh" "${modifies[@]}"
for t in $(chaines); do
  # shellcheck disable=SC2016  # développé par le bash -c
  etape "tests$(suffixe "$t")" bash -c '. .agents/checks/lib.sh; eval "r=\${${1}TEST_RACINE:-.}"; cd "$r" || exit 2; outil "${1}TEST"' _ "$(prefixe "$t")"
done
for fid in $(git log --format='%(trailers:key=Feature,valueonly)' "$plage" | tr -d ' ' | grep -v -x -e '' -e trivial | sort -u); do
  if ! a_du_contenu "$fid" "$plage"; then echo "CONTROLE ac-couverture $fid: NON APPLICABLE (planification seulement)"
  elif [ $conception -eq 1 ]; then echo "CONTROLE ac-couverture $fid: NON APPLICABLE (revue de conception : aucun code attendu)"
  else etape "ac-couverture $fid" "$C/ac-couverture.sh" "$fid"; fi
done
if command -v python3 >/dev/null 2>&1; then etape deps python3 "$C/deps-nouvelles.py" "$base_deps"
else echo "CONTROLE deps: UNVERIFIED (python3 absent)"; accepte deps || { [ $global -eq 0 ] && global=4; }; fi
for x in ${CONTROLES_SUPPL:-}; do etape "$x" bash -c ". .agents/checks/lib.sh; outil $x"; done
[ -n "${HARNESS:-}" ] && etape sync-agents "$C/sync-agents.sh" --check

case $global in 0) echo "RESULTAT: OK" ;; 4) echo "RESULTAT: UNVERIFIED" ;; *) echo "RESULTAT: FAIL" ;; esac
exit $global
