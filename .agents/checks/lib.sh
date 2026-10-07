# shellcheck shell=bash
# .agents/checks/lib.sh — sourcé par les scripts du socle. bash >= 3.2, aucune dépendance au harness.
# Codes de sortie du socle : 0 OK · 2 FAIL (bloquant) · 3 ESCALADE (§5.6) · 4 UNVERIFIED (bloquant, outil absent)
RACINE="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "FAIL : pas un dépôt git" >&2; exit 2; }
cd "$RACINE" || exit 2
# La configuration vient UNIQUEMENT de .agents/outils.env (protégé) : on efface d'abord toute variable du
# même nom héritée de l'environnement, pour qu'un « TEST_CMD=true git push » ne neutralise rien.
for v in $(compgen -v); do
  case "$v" in
    *_CMD|*_EXT|*_REQUIERT|*_RACINE|HARNESS|TOOLCHAINS|TESTS_GLOB|DEPS_AGE_MIN_JOURS|DEPS_APPROUVEES|CONTROLES_SUPPL|\
    CONTROLES_SECURITE|GATE_CRITIQUE_AGENTS|GATES_STANDARD|GATES_STRUCTUREL|PARTAGE_EXTERNE_AUTORISE|ACCEPTE_UNVERIFIED|\
    ACCEPTE_UNVERIFIED_LOCAL|CRITICITE|BRANCHE_PRINCIPALE|FORMAT_LINT_EXCLUDE|CODEOWNER|BASE) unset "$v" 2>/dev/null ;;
  esac
done
[ -f .agents/outils.env ] || { echo "FAIL : .agents/outils.env absent" >&2; exit 2; }
# shellcheck source=/dev/null
set -a; . ./.agents/outils.env; set +a

echec()       { echo "FAIL : $*" >&2; exit 2; }
non_verifie() { echo "UNVERIFIED : $*" >&2; exit 4; }

# outil NOM [args…] : exécute NOM_CMD (outils.env), suivi des arguments s'il y en a. Échec fermé : commande
# non configurée, ou binaire introuvable => UNVERIFIED (4). Binaires vérifiés : NOM_REQUIERT (liste) si
# défini, sinon le premier mot de la commande. Tout autre échec de l'outil => 2 : les codes 3 et 4 sont
# réservés au socle (pytest, par exemple, sort en 4 sur une erreur d'import : c'est un FAIL).
outil() {
  local nom="$1" cmd req b; shift
  eval "cmd=\${${nom}_CMD:-}; req=\${${nom}_REQUIERT:-}"
  [ -n "$cmd" ] || non_verifie "$nom non configuré (${nom}_CMD dans .agents/outils.env)"
  for b in ${req:-${cmd%% *}}; do
    command -v "$b" >/dev/null 2>&1 || non_verifie "outil introuvable : $b ($nom)"
  done
  [ -z "${SOCLE_TRACE:-}" ] || echo "\$ $cmd${1:+ <$# argument(s)>}" >&2     # preuve : commande exacte
  if [ $# -eq 0 ]; then eval "$cmd"; else eval "$cmd \"\$@\""; fi
  local c=$?; [ $c -eq 0 ] && return 0
  echo "FAIL : $nom a échoué (code de sortie $c)" >&2; return 2
}

# Chaînes d'outils. TOOLCHAINS vide : une seule chaîne, variables sans préfixe (TEST_CMD, LINT_EXT…).
# TOOLCHAINS="ts dart" : variables préfixées (TS_TEST_CMD, DART_LINT_EXT, DART_TEST_RACINE…), contrôles
# nommés « tests[dart] », « format-lint[ts] ».
# shellcheck disable=SC2086  # découpage voulu de la liste
chaines()  { if [ -z "${TOOLCHAINS:-}" ]; then echo -; else printf '%s\n' $TOOLCHAINS; fi; }
prefixe()  { [ "$1" = - ] || printf '%s_' "$1" | tr 'a-z-' 'A-Z_'; }
suffixe()  { [ "$1" = - ] || printf '[%s]' "$1"; }

# accepte <contrôle> : UNVERIFIED accepté par le dev (dette D-xxx) via ACCEPTE_UNVERIFIED (partout) ou
# ACCEPTE_UNVERIFIED_LOCAL (hors CI : variable CI vide). « tests » couvre « tests[dart] ». Jamais pour
# les secrets ; jamais en prod pour deps et CONTROLES_SECURITE.
accepte() {
  local nom="${1%%\[*}" liste="${ACCEPTE_UNVERIFIED:-}"
  [ -n "${CI:-}" ] || liste="$liste ${ACCEPTE_UNVERIFIED_LOCAL:-}"
  case " $liste " in *" $1 "*|*" $nom "*) ;; *) return 1 ;; esac
  [ "$nom" = secrets ] && return 1
  if [ "${CRITICITE:-prod}" = prod ]; then
    case " deps ${CONTROLES_SECURITE-SAST SCA CONTENEURS} " in *" $nom "*) return 1 ;; esac
  fi
  return 0
}

# empreinte_feature <F-id> <args git log>… : empreinte du contenu des commits « Feature: <F-id> » (hors
# traçabilité : MEMORY/, PROJECT_LOG.md, ROADMAP.md), stable par rebase. Un verdict vaut pour ce contenu-là.
empreinte_feature() {
  local fid="$1" c; shift
  for c in $(git log --no-merges --format='%H %(trailers:key=Feature,valueonly,separator=)' "$@" \
             | awk -v f="$fid" '{gsub(/ /,"",$2)} $2==f {print $1}'); do
    git show --format= "$c" -- . ':!MEMORY' ':!PROJECT_LOG.md' ':!ROADMAP.md' | git patch-id --stable | cut -d' ' -f1
  done | sort | git hash-object --stdin | cut -c1-12
}

# filtre_ext "ext1 ext2" fichier… : garde les fichiers existants dont l'extension est listée (liste vide = tout)
filtre_ext() {
  local exts="$1" f e; shift
  for f in "$@"; do
    [ -f "$f" ] || continue
    if [ -z "$exts" ]; then printf '%s\n' "$f"; continue; fi
    for e in $exts; do case "$f" in *."$e") printf '%s\n' "$f"; break ;; esac; done
  done
}
