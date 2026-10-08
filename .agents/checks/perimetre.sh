#!/bin/bash
# Usage : perimetre.sh --fichiers <agent> <fichier>…    écriture d'un agent (commit-msg, adaptateur harness)
#         perimetre.sh --commits <args git rev-list>…    chaque commit contre l'agent de son trailer « Agent: » ;
#           pour un merge : les fichiers que sa résolution change par rapport à la fusion automatique (git ≥ 2.36)
# Listes (.agents/perimetres/) : <agent>.txt · _commun.txt (traçabilité, tout agent ayant un périmètre)
#   _partage.txt (autorisé, signalé, revue CODEOWNERS au merge) · _protege.txt (« Agent: dev » uniquement)
#         perimetre.sh --couverture                      propriétaire(s) de chaque fichier suivi (à la génération)
# Un glob par ligne, liste blanche, mêmes règles que CODEOWNERS (GitHub) : « * » et « ? » restent dans un
# dossier, « ** » traverse ; un motif sans « / » vaut à toute profondeur (« *.md ») ; un « / » en tête ou au
# milieu l'ancre à la racine (« /Makefile », « src/*.py ») ; « docs/ », « docs » ou « docs/** » couvrent le
# dossier ; « docs/* » ne couvre que ses fichiers directs. Refusé (échec fermé, illisible pour CODEOWNERS) :
# espace, « ! », « [ », « \ », commentaire en fin de ligne, « ** » qui n'est pas un segment entier.
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
P=.agents/perimetres

re_de() { # re_de <glob> [fichier] : expression régulière étendue équivalente (motif déjà validé) ; « fichier » :
          # un nom couvre ce fichier seulement, pas un dossier du même nom (_commun.txt : traçabilité)
  local g="$1" ancre=0 dossier=0 re="" i=0 n c dernier
  case "$g" in /*) ancre=1; g="${g#/}" ;; esac
  case "$g" in */) dossier=1; g="${g%/}" ;; esac
  case "$g" in */*) ancre=1 ;; esac
  n=${#g}
  while [ "$i" -lt "$n" ]; do
    c="${g:$i:1}"
    case "$c" in
      '*') if [ "${g:$i:3}" = '**/' ]; then re="$re(.*/)?"; i=$((i + 3)); continue
           elif [ "${g:$i:2}" = '**' ]; then re="$re.*"; i=$((i + 2)); continue
           else re="${re}[^/]*"; fi ;;
      '?') re="${re}[^/]" ;;
      '.'|'+'|'('|')'|'|'|'{'|'}'|'^'|'$') re="$re\\$c" ;;
      *) re="$re$c" ;;
    esac
    i=$((i + 1))
  done
  [ $ancre -eq 1 ] || re="(.*/)?$re"
  dernier="${g##*/}"
  case "$dernier" in                      # le contenu d'un dossier : seulement si le dernier élément est un nom
    *'*'*|*'?'*) if [ $dossier -eq 1 ]; then re="$re/.*"            # « d*/ » : le contenu des dossiers
                 elif [ $ancre -eq 0 ]; then re="$re(/.*)?"; fi ;;    # « .semgrep* » : fichier ou dossier
                                                                      # « d/* » : fichiers directs seulement
    *) [ "${2:-}" = fichier ] || re="$re(/.*)?" ;;
  esac
  printf '^%s$\n' "$re"
}

# Toutes les listes sont traduites et validées ICI, dans le shell principal : une liste invalide arrête le
# script (échec fermé) au lieu de se réduire en silence à « rien n'est couvert ».
RE="$(mktemp -d)"; trap 'rm -rf "$RE"' EXIT
for l in "$P"/*.txt; do
  [ -f "$l" ] || continue
  out="$RE/$(basename "$l")"; : > "$out"; mode=""
  [ "$(basename "$l")" = _commun.txt ] && mode=fichier
  while IFS= read -r g || [ -n "$g" ]; do
    g="${g%$'\r'}"
    case "$g" in ''|\#*) continue ;; esac
    motif_valide "$g" || echec "$l : motif refusé « $g » (espace, !, [, \\, / seul, ** partiel ou commentaire en fin de ligne)"
    re_de "$g" $mode >> "$out"
  done < "$l"
  grep -E -f "$out" </dev/null >/dev/null 2>&1; [ $? -le 1 ] || echec "$l : expression invalide"
done
regex_liste() { printf '%s' "$RE/$(basename "$1")"; }   # regex_liste <liste> : fichier déjà construit

couvert() { # couvert <fichier> <liste>
  [ -f "$2" ] || return 1
  local r; r="$(regex_liste "$2")"
  [ -s "$r" ] && printf '%s\n' "$1" | grep -qE -f "$r"
}

relatif() { # chemin absolu ou Windows -> relatif à la racine ; « .. » refusé
  local f="${1//\\//}" r="${RACINE//\\//}" a rest=""
  case "$f" in                          # chemin absolu hors de RACINE (lien symbolique) : chemin physique
    /*) case "$f/" in "$r"/*) ;; *)
          a="$f"; while [ -n "$a" ] && [ ! -d "$a" ]; do rest="/${a##*/}$rest"; a="${a%/*}"; done
          if [ -n "$a" ] && a="$(cd "$a" 2>/dev/null && pwd -P)"; then f="$a$rest"; fi ;;
        esac ;;
  esac
  f="${f#"$r"/}"; f="${f#./}"
  case "/$f/" in */../*) echo ".." ;; *) echo "$f" ;; esac
}

statut() { # statut <agent> <fichier> -> OK | PARTAGE | HORS | PROTEGE   (ordre : protégé > partagé > propre)
  if couvert "$2" "$P/_protege.txt"; then [ "$1" = dev ] && echo OK || echo PROTEGE; return; fi
  [ "$1" = dev ] && { echo OK; return; }
  couvert "$2" "$P/_partage.txt" && { echo PARTAGE; return; }
  if couvert "$2" "$P/$1.txt" || couvert "$2" "$P/_commun.txt"; then echo OK; return; fi
  echo HORS
}

rc=0
CFG="${CONFIG_PROTEGEE-$CONFIG_PROTEGEE_DEFAUT}"; MIXTES=" "
for s in $CFG; do MIXTES="$MIXTES${s%%:*} "; done
config_ok() { # config_ok <avant> <apres> <fichier> [<avant2>] : clés protégées d'un fichier mixte inchangées
  case "$MIXTES" in *" ${3##*/} "*) ;; *) return 0 ;; esac
  command -v "${PYTHON_SOCLE:-python3}" >/dev/null 2>&1 \
    || { echo "PROTEGE : $3 : configuration protégée invérifiable (PYTHON_SOCLE introuvable)" >&2; return 1; }
  CONFIG_PROTEGEE="$CFG" "${PYTHON_SOCLE:-python3}" "$(dirname "$0")/config-protegee.py" "$@" </dev/null
}
signaler() { # signaler <statut> <fichier> <contexte>
  case "$1" in
    HORS|PROTEGE) echo "$1 : $2 ($3)" >&2; rc=2 ;;
    PARTAGE)      echo "À REVOIR (fichier partagé, revue CODEOWNERS) : $2 ($3)" >&2 ;;
  esac
}

case "${1:-}" in
  --fichiers)
    agent="${2:-}"; shift 2 || echec "usage : perimetre.sh --fichiers <agent> <fichier>…"
    [ "$agent" = dev ] || [ -f "$P/$agent.txt" ] || echec "agent sans périmètre déclaré : '$agent'"
    for f in "$@"; do
      f="$(relatif "$f")"; [ "$f" = ".." ] && echec "chemin contenant '..' refusé"
      signaler "$(statut "$agent" "$f")" "$f" "$agent"
      if [ "$agent" != dev ]; then config_ok HEAD : "$f" || rc=2; fi    # contenu indexé (commit-msg)
    done ;;
  --commits)
    shift
    commits="$(git rev-list --reverse "$@" 2>/dev/null)" \
      || echec "plage introuvable : $* (historique absent ? en CI, récupérer l'historique complet)"
    for c in $commits; do
      court="$(git log -1 --format=%h "$c")"
      if git rev-parse -q --verify "$c^3" >/dev/null; then              # octopus : --remerge-diff ne sait pas
        echo "Commit $court : merge à plus de deux parents refusé (fusionner une branche à la fois)" >&2; rc=2; continue
      fi
      if git rev-parse -q --verify "$c^2" >/dev/null; then              # merge
        res="$(git show --remerge-diff --no-renames --format= --name-only "$c" 2>/dev/null)" || echec "git ≥ 2.39 requis (--remerge-diff)"
        [ -n "$res" ] || continue                                        # fusion automatique : rien d'ajouté
      fi
      # exactement un « Agent: » et au plus un « Feature: » : les scripts lisent un trailer, pas une liste
      if [ "$(git log -1 --format='%(trailers:key=Agent,valueonly)' "$c" | grep -c .)" -gt 1 ] \
         || [ "$(git log -1 --format='%(trailers:key=Feature,valueonly)' "$c" | grep -c .)" -gt 1 ]; then
        echo "Commit $court : plusieurs trailers 'Agent:' ou 'Feature:' (un seul de chaque)" >&2; rc=2; continue
      fi
      agent="$(git log -1 --format='%(trailers:key=Agent,valueonly)' "$c" | head -n 1 | tr -d '[:space:]')"
      [ -n "$agent" ] || { echo "Commit $court sans trailer 'Agent:'" >&2; rc=2; continue; }
      [ "$agent" = dev ] || [ -f "$P/$agent.txt" ] || { echo "Commit $court : agent inconnu '$agent'" >&2; rc=2; continue; }
      fe="$(git log -1 --format='%(trailers:key=Feature,valueonly)' "$c" | tr -d '[:space:]')"
      if [ "$agent" != dev ] && [ -z "$fe" ]; then
        echo "Commit $court ($agent) sans trailer 'Feature:' (F-xxx ou trivial)" >&2; rc=2; continue
      fi
      if [ -n "$fe" ] && ! printf '%s\n' "$fe" | grep -qxE "$FEATURE_RE"; then
        echo "Commit $court : trailer « Feature: $fe » invalide (F-<nombre> ou trivial)" >&2; rc=2; continue
      fi
      if [ "$agent" != dev ]; then                                       # lien symbolique : le dev seul
        if git rev-parse -q --verify "$c^2" >/dev/null; then raw="$(git show --remerge-diff --raw --no-renames --format= "$c")"
        else raw="$(git diff-tree --no-commit-id --raw -r --root --no-renames "$c")"; fi
        if printf '%s\n' "$raw" | awk '$2 == "120000"' | grep -q .; then
          echo "Commit $court ($agent) : lien symbolique refusé (le dev seul en crée)" >&2; rc=2; continue
        fi
      fi
      avant="$(git rev-parse -q --verify "$c^" || git hash-object -t tree /dev/null)"
      p2="$(git rev-parse -q --verify "$c^2")"; base=""
      [ -z "$p2" ] || base="$(git merge-base --all "$c^1" "$c^2" 2>/dev/null | paste -sd, -)"
      [ -n "$p2" ] && [ -z "$base" ] && base="$(git hash-object -t tree /dev/null)"   # branches sans ancêtre commun
      while IFS= read -r f; do
        [ -n "$f" ] || continue
        signaler "$(statut "$agent" "$f")" "$f" "commit $court, $agent"
        # shellcheck disable=SC2086  # $p2 et $base vides hors merge
        if [ "$agent" != dev ]; then config_ok "$avant" "$c" "$f" $p2 $base || rc=2; fi
      done <<EOF
$(if git rev-parse -q --verify "$c^2" >/dev/null; then printf '%s\n' "$res"; else git diff-tree --no-commit-id --no-renames --name-only -r --root "$c"; fi)
EOF
    done ;;
  --couverture)        # à la génération : un grep par liste, puis le décompte par fichier
    tous="$RE/tous"; git ls-files > "$tous"
    : > "$RE/exclus"; : > "$RE/proprios"
    for l in "$P"/*.txt; do
      b="$(basename "$l" .txt)"; r="$(regex_liste "$l")"; [ -s "$r" ] || continue
      case "$b" in
        _*) grep -E -f "$r" "$tous" >> "$RE/exclus" ;;
        *)  grep -E -f "$r" "$tous" | sed "s|^|$b	|" >> "$RE/proprios" ;;
      esac
    done
    awk -F'\t' -v E="$RE/exclus" -v A="$RE/proprios" '
      BEGIN { while ((getline f < E) > 0) ex[f] = 1
              while ((getline l < A) > 0) { split(l, x, "\t"); n[x[2]]++; who[x[2]] = who[x[2]] " " x[1] } }
      !($0 in ex) { if (!($0 in n)) print "SANS PROPRIÉTAIRE : " $0
                    else if (n[$0] > 1) { print "PLUSIEURS PROPRIÉTAIRES :" who[$0] " : " $0; k++ } }
      END { exit (k > 0) ? 2 : 0 }' "$tous"; n=$?
    for l in "$P"/*.txt; do                 # motif qui ne couvre rien : fichier à venir, ou faute de frappe
      s=""
      # shellcheck disable=SC2094  # la liste n'est que lue
      while IFS= read -r g || [ -n "$g" ]; do
        g="${g%$'\r'}"; case "$g" in ''|\#*) continue ;; esac
        grep -qE "$(re_de "$g")" "$tous" || s="$s $g"
      done < "$l"
      [ -z "$s" ] || echo "GLOB SANS EFFET (fichier à venir ou faute de frappe ?) : $(basename "$l") :$s"
    done
    [ $n -eq 0 ] || echec "fichier(s) à plusieurs propriétaires : ils s'écraseront (§2.3)"
    echo "COUVERTURE : OK, aucun fichier suivi à plusieurs propriétaires ($(wc -l < "$tous" | tr -d ' ') fichiers ; ajouter les nouveaux avec git add avant)"
    exit 0 ;;
  *) echec "usage : perimetre.sh --fichiers <agent> <fichier>… | --commits <args rev-list>… | --couverture" ;;
esac
[ $rc -eq 0 ] || echo "Écriture refusée : demande au propriétaire du fichier ou au dev (§2.3)." >&2
exit $rc
