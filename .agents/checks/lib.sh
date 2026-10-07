# shellcheck shell=bash
# .agents/checks/lib.sh — sourcé par les scripts du socle. bash >= 3.2, aucune dépendance au harness.
# Codes de sortie du socle : 0 OK · 2 FAIL (bloquant) · 3 ESCALADE (§5.6) · 4 UNVERIFIED (bloquant, outil absent)
# Chemins non ASCII en clair dans toutes les sorties git du socle (sinon « src/\303\251t\303\251.py »).
# Avant tout appel à git : un GIT_CONFIG_COUNT hérité invalide ferait échouer git lui-même.
case "${GIT_CONFIG_COUNT:-0}" in *[!0-9]*|'') n_cfg=0 ;; *) n_cfg=$((10#${GIT_CONFIG_COUNT:-0})) ;; esac
export "GIT_CONFIG_KEY_$n_cfg=core.quotePath" "GIT_CONFIG_VALUE_$n_cfg=false"
export GIT_CONFIG_COUNT=$((n_cfg + 1))
RACINE="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "FAIL : pas un dépôt git" >&2; exit 2; }
cd "$RACINE" || exit 2
# La configuration vient UNIQUEMENT de .agents/outils.env (protégé) : on efface d'abord toute variable du
# même nom héritée de l'environnement, pour qu'un « TEST_CMD=true git push » ne neutralise rien.
for v in $(compgen -v); do
  case "$v" in
    *_CMD|*_EXT|*_REQUIERT|*_RACINE|HARNESS|TOOLCHAINS|TESTS_GLOB|DEPS_AGE_MIN_JOURS|DEPS_APPROUVEES|CONTROLES_SUPPL|\
    CONTROLES_SECURITE|GATE_CRITIQUE_AGENTS|GATES_STANDARD|GATES_STRUCTUREL|PARTAGE_EXTERNE_AUTORISE|ACCEPTE_UNVERIFIED|\
    ACCEPTE_UNVERIFIED_LOCAL|CRITICITE|BRANCHE_PRINCIPALE|FORMAT_LINT_EXCLUDE|CODEOWNER|PYTHON_SOCLE|BASE) unset "$v" 2>/dev/null ;;
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

# empreinte_feature <F-id> <args git log>… : empreinte du contenu que les gates de <F-id> ont à juger, hors
# traçabilité (MEMORY/, PROJECT_LOG.md, ROADMAP.md), stable par rebase. Y entrent : les commits « Feature:
# <F-id> » ; et, parmi les commits de la plage qui DESCENDENT d'un de ces commits, la résolution de chaque
# merge (quel que soit l'ordre des parents) et chaque commit d'agent sans feature ou « Feature: trivial »
# (du code glissé après la revue). N'y entrent pas : les commits d'une autre feature (ses propres gates)
# ni ceux du dev. Un verdict vaut pour ce contenu-là.
commits_feature() { # commits_feature <F-id> <args git log>… : commits « Feature: <F-id> » (hors merges)
  local fid="$1"; shift
  git log --no-merges --format='%H %(trailers:key=Feature,valueonly,separator=)' "$@" \
    | awk -v f="$fid" '{gsub(/ /,"",$2)} $2==f {print $1}'
}
apres_feature() { # apres_feature "<commits F>" <args git log>… : « M <merge> » / « C <commit> » à compter en plus
  local cs="$1"; shift
  git log --format='%H|%P|%(trailers:key=Agent,valueonly,separator=)|%(trailers:key=Feature,valueonly,separator=)' "$@" \
    | awk -F'|' -v s="$cs" '
      BEGIN { n = split(s, a, " "); for (i = 1; i <= n; i++) if (a[i] != "") F[a[i]] = 1 }
      { h = $1; np = split($2, p, " "); nb[h] = np; ag = $3; fe = $4; gsub(/[ \t]/, "", ag); gsub(/[ \t]/, "", fe)
        A[h] = ag; E[h] = fe; ord[++k] = h
        for (j = 1; j <= np; j++) kids[p[j]] = kids[p[j]] " " h }
      END { for (f in F) { q[++t] = f; vu[f] = 1 }
            for (hd = 1; hd <= t; hd++) { m = split(kids[q[hd]], x, " ")
              for (j = 1; j <= m; j++) if (!(x[j] in vu)) { vu[x[j]] = 1; q[++t] = x[j] } }
            for (i = 1; i <= k; i++) { h = ord[i]; if (!(h in vu) || (h in F)) continue
              if (nb[h] > 1) print "M " h
              else if (A[h] != "dev" && (E[h] == "" || E[h] == "trivial")) print "C " h } }'
}
empreinte_feature() {
  local fid="$1" cs c genre r; shift
  cs="$(commits_feature "$fid" "$@" | tr '\n' ' ')"
  {
    for c in $cs; do
      git show --format= "$c" -- . ':!MEMORY' ':!PROJECT_LOG.md' ':!ROADMAP.md' | git patch-id --stable | cut -d' ' -f1
    done
    [ -z "$cs" ] || apres_feature "$cs" "$@" | while read -r genre c; do
      if [ "$genre" = M ]; then
        r="$(git show --remerge-diff --format= "$c" -- . ':!MEMORY' ':!PROJECT_LOG.md' ':!ROADMAP.md')"
        [ -z "$r" ] || printf 'fusion %s\n' "$(printf '%s\n' "$r" | git hash-object --stdin)"
      else
        git show --format= "$c" -- . ':!MEMORY' ':!PROJECT_LOG.md' ':!ROADMAP.md' | git patch-id --stable | cut -d' ' -f1
      fi
    done
  } | sort | git hash-object --stdin | cut -c1-12
}

# spec_validee <spec> <rev> : la spec, à la révision <rev>, porte « Statut : validée » et le DERNIER commit
# qui en a changé le contenu est un commit du dev (validation ou revalidation, §6.0) ; un merge compte
# seulement si sa résolution touche la spec. Sinon : raison sur stdout, code 1.
spec_validee() {
  local a c
  git show "$2:$1" 2>/dev/null | grep -q '^Statut : validée' \
    || { echo "$1 n'est pas validée (ligne « Statut : validée » attendue, §6.0)"; return 1; }
  for c in $(git log --format=%H "$2" -- "$1"); do
    if git rev-parse -q --verify "$c^2" >/dev/null && [ -z "$(git show --remerge-diff --format= "$c" -- "$1")" ]; then
      continue                                                   # merge sans résolution sur la spec
    fi
    a="$(git log -1 --format='x%(trailers:key=Agent,valueonly,separator=)' "$c" | tr -d ' ')"; a="${a#x}"; break
  done
  [ "${a:-}" = dev ] || { echo "$1 modifiée en dernier par '${a:-?}' : elle doit être (re)validée par un commit 'Agent: dev' (§6.0)"; return 1; }
}

# a_du_contenu <F-id> <args git log>… : vrai si un commit de la feature touche autre chose que la
# planification et la traçabilité (specs/, ROADMAP.md, MEMORY/, PROJECT_LOG.md). Sinon, aucune exigence
# de test ni de gate : une PR qui n'apporte qu'une spec en brouillon reste verte.
a_du_contenu() {
  local fid="$1" c; shift
  for c in $(commits_feature "$fid" "$@"); do
    [ -n "$(git diff-tree --no-commit-id --name-only -r --root "$c" -- . ':!specs' ':!ROADMAP.md' ':!MEMORY' ':!PROJECT_LOG.md')" ] && return 0
  done
  return 1
}

# verdict_de <agent> < rapport : verdict lu sur la PREMIÈRE ligne non vide du rapport, au type de CET
# agent (route A et route B) ; rien d'autre ne compte, même un verdict cité plus loin. Les mentions du
# socle « INVALIDE (…) » et « UNVERIFIED (…) » passent telles quelles. Un gabarit recopié tel quel
# (« PASS | FAIL », « PASS / FAIL ») n'est pas un verdict. Type d'un gate : SECURITY, ARCHITECTURE, CRAFT
# pour les trois du socle ; sinon le nom de l'agent sans « agent- » (agent-perf => « PERF GATE: »).
# Sinon : vide (=> UNVERIFIED).
verdict_de() {
  local l v t
  l="$(grep -m1 -v '^[[:space:]]*$' | sed 's/^[#*[:space:]]*//; s/[*[:space:]]*$//')"
  v="$(printf '%s\n' "$l" | grep -oE '^(INVALIDE|UNVERIFIED) \(.*\)')"
  [ -n "$v" ] && { printf '%s\n' "$v"; return; }
  printf '%s\n' "$l" | grep -qE '(PASS|FAIL|UNVERIFIED|APPROVED|CHANGES_REQUESTED)[[:space:]]*[|/]' && { echo; return; }
  case "$1" in
    reviewer-*)       v="$(printf '%s\n' "$l" | grep -oE '^(APPROVED|CHANGES_REQUESTED|UNVERIFIED)([^A-Za-z_]|$)' | grep -oE '^[A-Z_]+')"
                      [ "$v" = UNVERIFIED ] && v="UNVERIFIED (contexte insuffisant pour le reviewer)"
                      printf '%s\n' "$v"; return ;;
    agent-securite)   t=SECURITY ;;
    agent-architecte) t=ARCHITECTURE ;;
    agent-craft)      t=CRAFT ;;
    *)                t="$(printf '%s' "${1#agent-}" | tr 'a-z-' 'A-Z_')" ;;
  esac
  printf '%s\n' "$l" | grep -oE "^$t GATE: (PASS|FAIL|UNVERIFIED)([^A-Za-z_]|\$)" | grep -oE "^$t GATE: [A-Z]+"
}

# motif_valide <ligne> : ligne d'une liste de périmètre que le socle ET CODEOWNERS lisent de la même façon.
# Refusés : espaces, « ! », crochets, « \ », commentaire en fin de ligne, « / » seul, et « ** » qui n'est pas
# un segment entier (« src/**.py » vaut « src/*.py » pour git et GitHub : ambigu).
motif_valide() {
  local m
  case "$1" in
    *[[:space:]]*|'!'*|*'['*|*\\*|?*'#'*|/) return 1 ;;
  esac
  m="/$1/"
  while case "$m" in */\*\*/*) true ;; *) false ;; esac; do m="${m//\/\*\*\//\/}"; done
  case "$m" in *'**'*) return 1 ;; esac
  return 0
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
