#!/bin/bash
# Usage : gates-verts.sh <args git log>…                 (CI : "<base>..HEAD", ou HEAD au premier push)
#         gates-verts.sh --si-principale <ref> <args>…   (pre-push : seulement vers BRANCHE_PRINCIPALE)
# Pour chaque feature des commits de la plage (hors « trivial ») : chaque gate requis — ceux de son tier
# (ligne « Tier : » de la spec ; GATES_STANDARD / GATES_STRUCTUREL dans outils.env) plus les reviewers de la
# ligne « Revue : » de la spec (un par domaine touché, §6.0) — a pour DERNIER verdict
# dans MEMORY/gates.log un PASS ou APPROVED sur le contenu actuel de la feature (empreinte, lib.sh), ou une
# DEROGATION D-xxx ajoutée par un commit « Agent: dev ». Attrape un gate oublié, rejeté ou périmé ; pas un
# journal falsifié : MEMORY/gates.log est revu par CODEOWNERS au merge (limite assumée, §2.3).
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
if [ "${1:-}" = --si-principale ]; then
  [ "$2" = "refs/heads/${BRANCHE_PRINCIPALE:-main}" ] || exit 0
  shift 2
fi
[ $# -gt 0 ] || echec "usage : gates-verts.sh <args git log>…"
features="$(git log --format='%(trailers:key=Feature,valueonly)' "$@" 2>/dev/null)" || echec "plage introuvable : $*"
J=MEMORY/gates.log; rc=0
ko() { echo "$1" >&2; rc=2; }
for fid in $(printf '%s\n' "$features" | tr -d ' ' | grep -v -x -e '' -e trivial | sort -u); do
  spec="specs/$fid.md"
  [ -f "$spec" ] || { ko "FAIL $fid : spec absente ($spec)"; continue; }
  tier="$(sed -n 's/^Tier : *\([a-z]*\).*/\1/p' "$spec" | head -n 1)"
  case "$tier" in
    trivial)    requis=""; var="" ;;
    standard)   requis="${GATES_STANDARD-}"; var=GATES_STANDARD ;;
    structurel) requis="${GATES_STRUCTUREL-}"; var=GATES_STRUCTUREL ;;
    *) ko "FAIL $fid : ligne « Tier : standard | structurel » absente de $spec"; continue ;;
  esac
  revue="$(sed -n 's/^Revue : *//p' "$spec" | head -n 1 | tr ',' ' ')"
  # shellcheck disable=SC2086  # listes de noms : découpage voulu
  requis="$(printf '%s ' $requis $revue)"
  if [ "$tier" != trivial ] && [ -z "${requis// /}" ]; then
    echo "UNVERIFIED $fid : $var vide dans outils.env" >&2; [ $rc -eq 0 ] && rc=4; continue
  fi
  e="$(empreinte_feature "$fid" "$@")"; manque=0
  for g in $requis; do
    ligne="$(grep -F " | $g | $fid | " "$J" 2>/dev/null | tail -n 1)"
    v="$(printf '%s' "$ligne" | awk -F' [|] ' '{print $4}')"; ve="$(printf '%s' "$ligne" | awk -F' [|] ' '{print $5}')"
    if [ -z "$ligne" ]; then ko "MANQUANT $fid : aucun verdict de $g (dossier-revue.sh $fid puis gate) [empreinte actuelle $e]"; manque=1; continue; fi
    case "$v" in
      *PASS|APPROVED) ;;
      DEROGATION*)
        a="$(git log -1 --format='x%(trailers:key=Agent,valueonly,separator=)' -S"$ligne" -- "$J" | tr -d ' ')"
        [ "${a#x}" = dev ] || { ko "FAIL $fid : dérogation de $g non ajoutée par un commit 'Agent: dev'"; manque=1; continue; } ;;
      *) ko "NON VERT $fid : dernier verdict de $g = $v [empreinte actuelle $e]"; manque=1; continue ;;
    esac
    [ "$ve" = "$e" ] || { ko "PÉRIMÉ $fid : $g a jugé un autre contenu ($ve, actuel $e) : relancer dossier-revue.sh puis le gate"; manque=1; }
  done
  [ $manque -eq 0 ] && echo "GATES $fid ($tier, $e) : OK (${requis% })"
done
[ $rc -eq 0 ] && echo "RESULTAT GATES: OK"
exit $rc
