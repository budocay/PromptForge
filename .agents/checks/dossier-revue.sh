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
# Diff montré aux gates : en texte (un octet NUL ne cache pas du code), sauf les fichiers .env (secrets
# présumés, jamais un fichier de code) et les binaires de média ou d'archive, chacun remplacé par une ligne
# « NON MONTRÉ » en tête du diff (§3.0).
BIN_EXT='png|jpe?g|gif|webp|avif|ico|bmp|tiff?|psd|pdf|woff2?|ttf|otf|eot|zip|gz|tgz|bz2|xz|7z|jar|mp3|mp4|m4a|webm|wav|ogg|flac|mov|avi'
retire=(); entete=""
while IFS="$(printf '\t')" read -r ajout _ f; do
  [ -n "$f" ] || continue
  case "$f" in
    *.js|*.mjs|*.cjs|*.ts|*.py|*.sh|*.rb|*.php|*.go|*.java|*.kt|*.dart|*.rs) ;;   # du code : toujours montré
    .env|*/.env|.env.*|*/.env.*) retire+=(":(exclude,literal)$f")
      entete="$entete# NON MONTRÉ (.env, secrets présumés) : $f"$'\n'; continue ;;
  esac
  { [ "$ajout" = - ] && printf '%s\n' "$f" | grep -qiE "\.($BIN_EXT)\$"; } || continue
  retire+=(":(exclude,literal)$f")
  entete="$entete# NON MONTRÉ (binaire média ou archive, $(git cat-file -s "HEAD:$f" 2>/dev/null || echo supprimé) octets) : $f"$'\n'
done <<EOF
$(git diff --numstat --no-renames "$base" HEAD)
EOF
{ printf '%s' "$entete"
  git diff --no-ext-diff --no-textconv --no-renames --text -U30 "$base" HEAD -- . "${retire[@]}"; } > "$d/diff.patch"
empreinte_feature "$fid" "$base..HEAD" > "$d/empreinte"
echo "$fid $(cat "$d/empreinte")" > .agents/.state/dossier-courant
echo "${mode:+conception}" > "$d/mode"
# shellcheck disable=SC2086  # $mode vide ou --conception
"$(dirname "$0")/controles.sh" $mode "$base" > "$d/checks.txt" 2>&1; code=$?
echo "Dossier : $d (${mode:+conception, }base $(git log -1 --format=%h "$base"), empreinte $(cat "$d/empreinte"), contrôles : code $code)"
exit $code
