#!/bin/bash
# Usage : perimetre.sh --fichiers <agent> <fichier>…    écriture d'un agent (commit-msg, adaptateur harness)
#         perimetre.sh --commits <args git rev-list>…    chaque commit contre l'agent de son trailer « Agent: » ;
#           pour un merge : les fichiers que sa résolution change par rapport à la fusion automatique (git ≥ 2.36)
# Listes (.agents/perimetres/) : <agent>.txt · _commun.txt (traçabilité, tout agent ayant un périmètre)
#   _partage.txt (autorisé, signalé, revue CODEOWNERS au merge) · _protege.txt (« Agent: dev » uniquement)
# Un glob par ligne, liste blanche ; dans [[ ]], * traverse aussi les /.
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
P=.agents/perimetres

couvert() { # couvert <fichier> <liste>
  [ -f "$2" ] || return 1
  local g
  while IFS= read -r g || [ -n "$g" ]; do
    case "$g" in ''|\#*) continue ;; esac
    # shellcheck disable=SC2053  # correspondance de glob voulue
    [[ "$1" == $g ]] && return 0
  done < "$2"
  return 1
}

relatif() { # chemin absolu ou Windows -> relatif à la racine ; « .. » refusé
  local f="${1//\\//}" r="${RACINE//\\//}"
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
    done ;;
  --commits)
    shift
    commits="$(git rev-list --reverse "$@" 2>/dev/null)" \
      || echec "plage introuvable : $* (historique absent ? en CI, récupérer l'historique complet)"
    for c in $commits; do
      court="$(git log -1 --format=%h "$c")"
      if git rev-parse -q --verify "$c^2" >/dev/null; then              # merge
        res="$(git show --remerge-diff --format= --name-only "$c" 2>/dev/null)" || echec "git ≥ 2.36 requis (--remerge-diff)"
        [ -n "$res" ] || continue                                        # fusion automatique : rien d'ajouté
      fi
      agent="$(git log -1 --format='%(trailers:key=Agent,valueonly)' "$c" | head -n 1 | tr -d '[:space:]')"
      [ -n "$agent" ] || { echo "Commit $court sans trailer 'Agent:'" >&2; rc=2; continue; }
      [ "$agent" = dev ] || [ -f "$P/$agent.txt" ] || { echo "Commit $court : agent inconnu '$agent'" >&2; rc=2; continue; }
      while IFS= read -r f; do
        [ -n "$f" ] && signaler "$(statut "$agent" "$f")" "$f" "commit $court, $agent"
      done <<EOF
$(if git rev-parse -q --verify "$c^2" >/dev/null; then printf '%s\n' "$res"; else git diff-tree --no-commit-id --name-only -r --root "$c"; fi)
EOF
    done ;;
  *) echec "usage : perimetre.sh --fichiers <agent> <fichier>… | --commits <args rev-list>…" ;;
esac
[ $rc -eq 0 ] || echo "Écriture refusée : demande au propriétaire du fichier ou au dev (§2.3)." >&2
exit $rc
