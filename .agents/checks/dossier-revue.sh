#!/bin/bash
# Usage : dossier-revue.sh [--conception] <F-id>
# Construit .agents/review/<F-id>/ (spec.md, diff.patch, checks.txt, empreinte) : la SEULE base de
# jugement des gates (§3.0). La base n'est pas un paramètre : c'est le point de divergence avec la branche
# principale (origin/BRANCHE_PRINCIPALE, ou la branche locale si le dépôt n'a aucun remote).
# --conception : revue de la conception d'un changement structurel, avant le code (§6.1).
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
mode=""; [ "${1:-}" = --conception ] && { mode=--conception; shift; }
fid="${1:?usage : dossier-revue.sh [--conception] <F-id>}"; spec="specs/$fid.md"
[ -f "$spec" ] || echec "spec absente : $spec"
# La spec est un contrat : le DERNIER commit qui la modifie doit être un commit du dev (validation ou
# revalidation). Une spec retouchée après validation, par qui que ce soit d'autre, est refusée.
raison="$(spec_validee "$spec" HEAD)" || echec "$raison"
[ -z "$(git status --porcelain -- . ':!MEMORY/gates.log')" ] || echec "arbre non commité : commite (trailers Agent:/Feature:) avant la revue"
B="${BRANCHE_PRINCIPALE:?BRANCHE_PRINCIPALE absent de outils.env}"
if git rev-parse --verify --quiet "origin/$B^{commit}" >/dev/null; then cible="origin/$B"
elif [ -z "$(git remote)" ]; then cible="$B"                        # dépôt local sans remote
else echec "origin/$B introuvable (git fetch)"; fi
base="$(git merge-base HEAD "$cible" 2>/dev/null)" || echec "pas de point commun avec $cible"
features_de "$base..HEAD" | grep -qx -- "$fid" \
  || echec "aucun commit 'Feature: $fid' depuis $cible (travailler sur une branche de feature) : rien à revoir"
d=".agents/review/$fid"; rm -rf "$d"; mkdir -p "$d" .agents/.state
cp "$spec" "$d/spec.md"
git diff --no-ext-diff --no-textconv --text -U30 "$base" HEAD -- . ':(exclude,glob)**/.env*' ':(exclude,glob)**/secrets/**' > "$d/diff.patch"
empreinte_feature "$fid" "$base..HEAD" > "$d/empreinte"
echo "$fid $(cat "$d/empreinte")" > .agents/.state/dossier-courant
echo "${mode:+conception}" > "$d/mode"
# shellcheck disable=SC2086  # $mode vide ou --conception
"$(dirname "$0")/controles.sh" $mode "$base" > "$d/checks.txt" 2>&1; code=$?
echo "Dossier : $d (${mode:+conception, }base $(git log -1 --format=%h "$base"), empreinte $(cat "$d/empreinte"), contrôles : code $code)"
exit $code
