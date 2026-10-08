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
# Diff montré aux gates : en texte (un octet NUL ne cache pas du code). Deux exceptions (§3.0) :
# - un fichier nommé exactement .env ou .env.<x> qui n'est pas du code : montré en entier, valeurs des clés
#   sensibles masquées (un segment KEY, SECRET, TOKEN, PASS, PASSWORD, PWD, CREDENTIALS, PRIVATE, APIKEY ou
#   DSN dans le nom de la clé ; identifiants dans une URL « ://u:p@ ») ;
# - un binaire de média ou d'archive dont la signature est celle d'un média ET dont au moins 30 % des octets
#   ne sont pas du texte : résumé, ses suites de 6 caractères imprimables ou blancs montrées (4 Kio au plus :
#   un polyglotte laisse voir son code, une police ou un PDF ne sature pas le dossier).
BIN_EXT='png|jpe?g|gif|webp|ico|bmp|pdf|woff2?|ttf|otf|zip|gz|tgz|jar|mp3|mp4|webm|ogg|flac|wav'
CODE_EXT=" js mjs cjs ts tsx jsx mts cts vue svelte py sh bash rb php go java kt kts dart rs swift c cc cpp h cs ${LINT_EXT:-} ${FORMAT_EXT:-} "
media() { # media <chemin> : vrai si les premiers octets de HEAD:<chemin> sont une signature de média ou d'archive
  local t; t="$(git cat-file -p "HEAD:$1" 2>/dev/null | head -c 12 | od -An -tx1 | tr -d ' \n')"
  case "$t" in
    89504e47*|ffd8ff*|47494638*|52494646????????57454250*|00000100*|424d*|25504446*|774f4646*|774f4632*|00010000*|\
    4f54544f*|504b0304*|1f8b*|494433*|fffb*|????????66747970*|1a45dfa3*|4f676753*|664c6143*|52494646????????57415645*) return 0 ;;
  esac
  return 1
}
retire=(); entete=""; extraits=""
while IFS="$(printf '\t')" read -r ajout _ f; do
  [ -n "$f" ] || continue
  b="${f##*/}"
  case "$b" in
    .env|.env.*) case "$CODE_EXT" in *" ${b##*.} "*) ;; *)
        retire+=(":(exclude,literal)$f"); entete="$entete# MONTRÉ EN FIN DE DIFF, VALEURS SENSIBLES MASQUÉES (.env) : $f"$'\n'
        extraits="$extraits# CONTENU DE $f (valeurs des clés sensibles masquées) :"$'\n'"$(git cat-file -p "HEAD:$f" 2>/dev/null \
          | awk '{ u = toupper($0)
                   if (match(u, /^[ \t]*(EXPORT[ \t]+)?([A-Z0-9.]*_)*(KEY|SECRET|TOKEN|PASS|PASSWORD|PASSWD|PWD|CREDENTIALS?|PRIVATE|APIKEY|DSN)(_[A-Z0-9.]*)*[ \t]*[=:]/))
                     { print substr($0, 1, RLENGTH) "***"; next }
                   gsub(/:\/\/[^\/@ ]*:[^\/@ ]*@/, "://***@"); print }')"$'\n'
        continue ;; esac ;;
  esac
  { [ "$ajout" = - ] && printf '%s\n' "$f" | grep -qiE "\.($BIN_EXT)\$"; } || continue
  if ! git cat-file -e "HEAD:$f" 2>/dev/null; then                     # binaire supprimé
    retire+=(":(exclude,literal)$f"); entete="$entete# NON MONTRÉ (binaire supprimé) : $f"$'\n'; continue
  fi
  media "$f" || continue
  taille="$(git cat-file -s "HEAD:$f")"
  autres="$(git cat-file -p "HEAD:$f" | LC_ALL=C tr -d '\t\n\r\040-\176' | wc -c | tr -d ' ')"
  [ $((autres * 100)) -ge $((taille * 30)) ] || continue               # surtout du texte : montré en entier
  retire+=(":(exclude,literal)$f")
  entete="$entete# NON MONTRÉ (média ou archive, $taille octets ; texte lisible en fin de diff) : $f"$'\n'
  lisible="$(git cat-file -p "HEAD:$f" | LC_ALL=C tr '\000' '\n' | LC_ALL=C grep -aoE '[[:print:][:space:]]{6,}')"
  extraits="$extraits# TEXTE LISIBLE DE $f :"$'\n'"$(printf '%s' "$lisible" | head -c 4096)"$'\n'
  [ "${#lisible}" -le 4096 ] || extraits="$extraits# TEXTE LISIBLE TRONQUÉ à 4 Kio sur ${#lisible} : un code qui charge ce fichier est un FAIL (§3.0)"$'\n'
done <<EOF
$(git diff --numstat --no-renames "$base" HEAD)
EOF
{ printf '%s' "$entete"
  git diff --no-ext-diff --no-textconv --no-renames --text -U30 "$base" HEAD -- . "${retire[@]}"
  printf '%s' "$extraits"; } > "$d/diff.patch"
empreinte_feature "$fid" "$base..HEAD" > "$d/empreinte"
echo "$fid $(cat "$d/empreinte")" > .agents/.state/dossier-courant
echo "${mode:+conception}" > "$d/mode"
# shellcheck disable=SC2086  # $mode vide ou --conception
"$(dirname "$0")/controles.sh" $mode "$base" > "$d/checks.txt" 2>&1; code=$?
echo "Dossier : $d (${mode:+conception, }base $(git log -1 --format=%h "$base"), empreinte $(cat "$d/empreinte"), contrôles : code $code)"
exit $code
