#!/bin/bash
# Usage : gates-verts.sh [--rev <commit>] <args git log>…        (CI : "<base>..HEAD", ou HEAD au premier push)
#         gates-verts.sh --si-principale <ref> --rev <commit> <args>…  (pre-push : vers BRANCHE_PRINCIPALE)
# Spec et journal sont lus DANS le commit jugé (--rev, HEAD par défaut), jamais dans l'arbre de travail.
# La spec doit être validée par le dev à ce commit (spec_validee, lib.sh) : sinon ses lignes « Tier : » et
# « Revue : » ne valent rien.
# Pour chaque feature des commits de la plage (hors « trivial », et hors planification seule : commits qui
# ne touchent que specs/, ROADMAP.md, MEMORY/, PROJECT_LOG.md) : chaque gate requis — ceux de son tier
# (ligne « Tier : » de la spec ; GATES_STANDARD / GATES_STRUCTUREL dans outils.env) plus les reviewers de la
# ligne « Revue : » de la spec (un par domaine touché, §6.0) — a pour DERNIER verdict
# dans MEMORY/gates.log un PASS ou APPROVED sur le contenu actuel de la feature (empreinte, lib.sh), ou une
# DEROGATION D-xxx ajoutée par un commit « Agent: dev ». Attrape un gate oublié, rejeté ou périmé ; pas un
# journal falsifié : MEMORY/gates.log est revu par CODEOWNERS au merge (limite assumée, §2.3).
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
rev=HEAD
if [ "${1:-}" = --si-principale ]; then
  [ "$2" = "refs/heads/${BRANCHE_PRINCIPALE:-main}" ] || exit 0
  shift 2
fi
if [ "${1:-}" = --rev ]; then rev="${2:?usage : --rev <commit>}"; shift 2; fi
[ $# -gt 0 ] || echec "usage : gates-verts.sh [--rev <commit>] <args git log>…"
git rev-parse --verify --quiet "$rev^{commit}" >/dev/null || echec "commit introuvable : $rev"
git rev-list "$@" >/dev/null 2>&1 || echec "plage introuvable : $*"
J=MEMORY/gates.log; rc=0
journal="$(git show "$rev:$J" 2>/dev/null)"
ko() { echo "$1" >&2; rc=2; }
while IFS= read -r v; do
  [ -z "$v" ] || ko "FAIL : trailer « Feature: $v » invalide (F-<nombre> ou trivial)"
done <<EOF
$(valeurs_feature "$@" | grep -vxE "$FEATURE_RE")
EOF
set -f                                              # aucune valeur ne s'étend en noms de fichiers
for fid in $(features_de "$@"); do
  spec="specs/$fid.md"
  a_du_contenu "$fid" "$@" || { echo "GATES $fid : planification seulement (spec, ROADMAP), aucun gate requis"; continue; }
  git cat-file -e "$rev:$spec" 2>/dev/null || { ko "FAIL $fid : spec absente ($spec)"; continue; }
  raison="$(spec_validee "$spec" "$rev")" || { ko "FAIL $fid : $raison"; continue; }
  contenu="$(git show "$rev:$spec")"
  tier="$(printf '%s\n' "$contenu" | sed -n 's/^Tier : *\([a-z]*\).*/\1/p' | head -n 1)"
  case "$tier" in
    trivial)    ko "FAIL $fid : « Tier : trivial » dans une spec (un changement trivial n'a pas de spec, §6.0 : commits « Feature: trivial »)"; continue ;;
    standard)   requis="${GATES_STANDARD-}"; var=GATES_STANDARD ;;
    structurel) requis="${GATES_STRUCTUREL-}"; var=GATES_STRUCTUREL ;;
    *) ko "FAIL $fid : ligne « Tier : standard | structurel » absente de $spec"; continue ;;
  esac
  revue="$(printf '%s\n' "$contenu" | sed -n 's/^Revue : *//p' | head -n 1 | tr ',' ' ')"
  # shellcheck disable=SC2086  # listes de noms : découpage voulu
  requis="$(printf '%s ' $requis $revue)"
  if [ "$tier" != trivial ] && [ -z "${requis// /}" ]; then
    echo "UNVERIFIED $fid : $var vide dans outils.env" >&2; [ $rc -eq 0 ] && rc=4; continue
  fi
  e="$(empreinte_feature "$fid" "$@")"; manque=0
  for g in $requis; do
    ligne="$(printf '%s\n' "$journal" | grep -F " | $g | $fid | " | tail -n 1)"
    v="$(printf '%s' "$ligne" | awk -F' [|] ' '{print $4}')"; ve="$(printf '%s' "$ligne" | awk -F' [|] ' '{print $5}')"
    if [ -z "$ligne" ]; then ko "MANQUANT $fid : aucun verdict de $g (dossier-revue.sh $fid puis gate) [empreinte actuelle $e]"; manque=1; continue; fi
    case "$v" in
      *PASS|APPROVED) ;;
      DEROGATION*)
        a="$(git log -1 --format='x%(trailers:key=Agent,valueonly,separator=)' "$rev" -S"$ligne" -- "$J" | tr -d ' ')"
        [ "${a#x}" = dev ] || { ko "FAIL $fid : dérogation de $g non ajoutée par un commit 'Agent: dev'"; manque=1; continue; } ;;
      *) ko "NON VERT $fid : dernier verdict de $g = $v [empreinte actuelle $e]"; manque=1; continue ;;
    esac
    [ "$ve" = "$e" ] || { ko "PÉRIMÉ $fid : $g a jugé un autre contenu ($ve, actuel $e) : relancer dossier-revue.sh puis le gate"; manque=1; }
  done
  [ $manque -eq 0 ] && echo "GATES $fid ($tier, $e) : OK (${requis% })"
done
# Pour la relecture humaine : code d'agent sans gate (« Feature: trivial »), dont le dev confirme le tier (§6.0)
git log --format='%H|%h|%(trailers:key=Agent,valueonly,separator=)|%(trailers:key=Feature,valueonly,separator=)' "$@" \
  | while IFS='|' read -r h hc ag fe; do
      ag="${ag// /}"; fe="${fe// /}"
      { [ "$fe" = trivial ] && [ "$ag" != dev ]; } || continue
      f="$(contenu_de "$h" | sed -n 's%^diff --git a/\([^ ]*\) .*%\1%p' | head -n 3 | tr '\n' ' ')"
      [ -z "$f" ] || echo "TRIVIAL (sans gate, tier à confirmer par le dev à la relecture) : $hc $ag : $f"
    done
[ $rc -eq 0 ] && echo "RESULTAT GATES: OK"
exit $rc
