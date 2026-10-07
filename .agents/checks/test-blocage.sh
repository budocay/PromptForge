#!/bin/bash
# Usage : test-blocage.sh
# Test de blocage obligatoire (§4.2), en trois parties :
#   1. outillage réel : chaque commande de outils.env est trouvable dans CE PATH (lancer depuis le harness :
#      c'est le PATH que verront les hooks) ; intégrité du socle si .agents/SOCLE.sha256 existe ;
#   2. plomberie : rejoue chaque violation dans un clone jetable et vérifie qu'elle est BLOQUÉE, pour la
#      raison affichée sous « ↳ », et qu'un changement conforme PASSE. Tests, formateur et linter y sont
#      remplacés par des témoins (la partie 1 couvre les vrais) ; le scanner de secrets est le vrai ;
#   3. adaptateur Claude Code, s'il est présent.
# Lecture : « [OK] » = comportement attendu ; « [KO] » = trou à corriger avant de faire confiance au socle.
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
command -v "${SECRETS_STDIN_CMD%% *}" >/dev/null 2>&1 || non_verifie "scanner de secrets introuvable : test impossible"
ko=0

echo "== 1. Outillage réel"
for v in $(compgen -v | sed -n 's/_CMD$//p' | sort -u); do        # toutes les commandes lues dans outils.env
  eval "cmd=\${${v}_CMD:-}; req=\${${v}_REQUIERT:-}"; [ -n "$cmd" ] || continue
  n="$v"; tc=-
  for t in $(chaines); do p="$(prefixe "$t")"; case "$v" in "$p"?*) [ -n "$p" ] && { n="${v#"$p"}"; tc="$t"; } ;; esac; done
  case "$n" in TEST|TEST_SETUP) c=tests ;; FORMAT_CHECK|LINT) c=format-lint ;; SECRETS_*) c=secrets ;; *) c="$n" ;; esac
  c="$c$(suffixe "$tc")"; manque=""
  for b in ${req:-${cmd%% *}}; do command -v "$b" >/dev/null 2>&1 || manque="$manque $b"; done
  if [ -z "$manque" ]; then echo "[OK] $v : trouvé"
  elif accepte "$c"; then echo "[OK] $v : absent ($manque ), UNVERIFIED accepté par le dev pour « $c »"
  else echo "[KO] $v : introuvable dans ce PATH :$manque (chemin absolu dans outils.env, ou PATH du harness)"; ko=1; fi
done
if ! ( printf '' | outil SECRETS_STDIN ) >/dev/null 2>&1; then
  echo "[KO] SECRETS_STDIN : le scanner ne fonctionne pas sur une entrée vide (version trop ancienne ? gitleaks >= 8.19 pour stdin/git)"; ko=1
fi
py="${PYTHON_SOCLE:-python3}"
if ! "$py" -c 'import tomllib' >/dev/null 2>&1; then
  if accepte deps; then echo "[OK] PYTHON_SOCLE : $py absent ou < 3.11, UNVERIFIED accepté par le dev pour « deps »"
  else echo "[KO] PYTHON_SOCLE : $py absent ou < 3.11 (deps-nouvelles.py a besoin de tomllib)"; ko=1; fi
fi
if [ -x .claude/hooks/cc-adapt.sh ] && ! command -v jq >/dev/null 2>&1; then
  echo "[KO] jq : introuvable, alors que l'adaptateur Claude Code en dépend (il bloque tout sans lui)"; ko=1
fi
if [ -f .agents/SOCLE.sha256 ]; then
  sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }
  diff=""; while read -r h f; do [ -f "$f" ] && [ "$(sha "$f")" = "$h" ] || diff="$diff $f"; done < .agents/SOCLE.sha256
  if [ -z "$diff" ]; then echo "[INFO] socle identique à la version extraite (.agents/SOCLE.sha256)"
  else echo "[INFO] socle modifié depuis l'extraction (attendu seulement après une décision du dev) :$diff"; fi
fi

echo "== 2. Plomberie (clone jetable)"
# Témoin : un PRODUCTEUR dont le périmètre a un glob de dossier « d/** » ou « d/*.ext » (les agents de
# planification, de veille et de conception ne produisent pas de code : les cas de gate n'auraient pas de sens).
agent=""; pref=""; ext=""
for f in .agents/perimetres/*.txt; do
  case "$(basename "$f")" in _*|orchestrateur.txt|agent-planif.txt|agent-veille.txt|agent-architecte-conception.txt) continue ;; esac
  # formes acceptées : d/  d/**  d/*.ext  d/**/*.ext  (d sans joker, « / » en tête permis)
  g="$(tr -d '\r' < "$f" | grep -E '^/?[^#*?/][^*?]*(/|/\*\*|/\*\.[A-Za-z0-9]+|/\*\*/\*\.[A-Za-z0-9]+)$' | head -n 1)"
  [ -n "$g" ] || continue
  agent="$(basename "$f" .txt)"; g="${g#/}"
  case "$g" in
    */\*\*/\*.*) pref="${g%%/\*\**}"; ext=".${g##*.}" ;;
    */\*.*)      pref="${g%/*}"; ext=".${g##*.}" ;;
    */\*\*)       pref="${g%/\*\*}"; ext="" ;;
    */)          pref="${g%/}"; ext="" ;;
  esac
  break
done
[ -n "$agent" ] || echec "aucun producteur avec un glob de dossier (« d/ », « d/** », « d/*.ext » ou « d/**/*.ext ») : test impossible"
chemin()  { printf '%s/temoin%s%s' "$pref" "$1" "$ext"; }        # chemin dans le périmètre du témoin
dedans="$(chemin "")"; rouge="$(chemin -ROUGE)"; da="$(chemin -a)"; db="$(chemin -b)"; dc="$(chemin -c)"
protege="$(grep -v -e '^#' -e '^$' .agents/perimetres/_protege.txt 2>/dev/null | head -n 1 | sed 's#^/##; s/\*\*/x/g; s/\*/x/g')"
cle_aws="AKIA""QYLPMN5HHHFPZAM2"                               # clé factice au format AWS, assemblée à
P="${BRANCHE_PRINCIPALE:-main}"                                # l'exécution : ce fichier passe son propre scan

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
if ! git clone -q --no-local "$RACINE" "$T/depot" || ! git init -q --bare "$T/distant.git"; then echec "clone impossible"; fi
cd "$T/depot" || exit 2
git config user.email test@blocage.invalid; git config user.name test-blocage; git config core.hooksPath .githooks
git remote set-url origin "$T/distant.git"
# shellcheck disable=SC2016  # le test témoin est écrit tel quel
printf '%s\n' 'test -z "$(find . -name "*ROUGE*" -not -path "./.git/*")" || { echo "not ok - test témoin rouge"; exit 1; }' > zz-test-temoin.sh
cat >> .agents/outils.env <<'EOF'
TOOLCHAINS=""
TEST_CMD="sh zz-test-temoin.sh"
TEST_SETUP_CMD=""
TEST_REQUIERT=""
FORMAT_CHECK_CMD="true"
FORMAT_CHECK_REQUIERT=""
LINT_CMD="true"
LINT_REQUIERT=""
GATES_STANDARD="zz-gate-temoin"
ACCEPTE_UNVERIFIED=""
ACCEPTE_UNVERIFIED_LOCAL=""
TESTS_GLOB="zz-tests/**"
EOF
# gate témoin dont la réponse cite APPROVED après une première ligne qui n'est pas un verdict
printf '%s\n' 'cat >/dev/null' 'echo "Verdict : CHANGES_REQUESTED"' 'echo "* APPROVED une fois corrigé"' > zz-gate-ambigu.sh
mkdir -p specs; printf '# SPEC F-900 — témoin\n\nStatut : validée\nTier : standard\n\n- F-900-AC1 : témoin.\n' > specs/F-900.md
git add -A && git commit -q --no-verify -m "témoin" --trailer "Agent: dev" && git push -q --no-verify origin HEAD:"$P" 2>/dev/null
git fetch -q origin; base="$(git rev-parse HEAD)"

attendu() { # attendu <bloque|passe> <libellé> <commande…>
  local voulu="$1" lib="$2"; shift 2
  if "$@" >"$T/sortie" 2>&1; then obtenu=passe; else obtenu=bloque; fi
  if [ "$obtenu" = "$voulu" ]; then echo "[OK] $lib : $obtenu"
    [ "$obtenu" = bloque ] && echo "     ↳ $(grep -v -e '^ *$' -e '^error: failed to push' -e '^Écriture refusée : demande' "$T/sortie" | grep -iE 'fail|hors|protege|unverified|introuvable|secret|escalade|not ok|modifi|manquant|PÉRIMÉ|inconnu|absent|refusé|trailer' | tail -n 1)"
  else echo "[KO] $lib : attendu $voulu, obtenu $obtenu"; sed 's/^/     /' "$T/sortie" | tail -n 5; ko=1; fi
  git reset -q --hard "$base"; git clean -qfdx -e .agents/.state
  git push -q -f --no-verify origin "$base:refs/heads/$P" 2>/dev/null     # le distant revient à la base
}
# shellcheck disable=SC2329  # fonctions transmises aux sous-shells par declare -f
ecrire()  { mkdir -p "$(dirname "$1")"; printf '%s\n' "$2" > "$1"; git add -A; }
# shellcheck disable=SC2329
commit()  { git commit -q -m "$1" --trailer "Agent: $2" --trailer "Feature: trivial" "${@:3}"; }
# shellcheck disable=SC2329
commitf() { git commit -q -m "$1" --trailer "Agent: $2" --trailer "Feature: $3" "${@:4}"; }
# shellcheck disable=SC2329
regle()   { printf '%s\n' "$@" >> .agents/outils.env; }
F="$(declare -f ecrire commit commitf regle)"
pousser="git push -q origin HEAD:$P"
revue_zz="mkdir -p .agents/agents .agents/review/F-900 MEMORY && printf -- '---\\nname: reviewer-zz\\n---\\nRevue.\\n' > .agents/agents/reviewer-zz.md && printf 'RESULTAT: OK\\n' > .agents/review/F-900/checks.txt && : > .agents/review/F-900/spec.md && : > .agents/review/F-900/diff.patch && echo e2e2e2e2e2e2 > .agents/review/F-900/empreinte"
verdict="mkdir -p MEMORY; e=\$(bash -c '. .agents/checks/lib.sh; empreinte_feature F-900 origin/$P..HEAD'); echo \"2026-01-01T00:00:00Z | zz-gate-temoin | F-900 | APPROVED | \$e\" >> MEMORY/gates.log; git add -A; commitf journal $agent F-900"

attendu passe  "dépôt : son propre historique passe le scan de secrets" .agents/checks/secrets.sh --plage HEAD
attendu bloque "pre-commit : secret indexé"                     bash -c "$F; ecrire '$dedans' 'k = \"$cle_aws\"'; commit t $agent"
attendu bloque "commit-msg : trailer Agent absent"              bash -c "$F; ecrire '$dedans' ok; git commit -q -m t"
attendu bloque "commit-msg : trailer Feature absent (agent)"    bash -c "$F; ecrire '$dedans' ok; git commit -q -m t --trailer 'Agent: $agent'"
attendu bloque "commit-msg : écriture hors périmètre"           bash -c "$F; ecrire zz-hors-perimetre.txt ok; commit t $agent"
[ -n "$protege" ] && \
attendu bloque "commit-msg : fichier protégé"                   bash -c "$F; ecrire '$protege' ok; commit t $agent"
attendu bloque "pre-push : commit rouge + correctif non commité" bash -c "$F; ecrire '$rouge' x; commit t $agent && rm '$rouge' && $pousser"
attendu bloque "pre-push : secret commité puis supprimé"        bash -c "$F; ecrire '$dedans' 'k = \"$cle_aws\"'; commit t $agent --no-verify && ecrire '$dedans' ok && commit t2 $agent && $pousser"
attendu bloque "pre-push : commit hors périmètre (--no-verify)" bash -c "$F; ecrire zz-hors.txt ok; commit t $agent --no-verify && $pousser"
attendu bloque "pre-push : secret ajouté dans la résolution d'un merge" bash -c "$F; git checkout -q -b zz-cote; ecrire '$db' ok; commit t $agent; git checkout -q -; ecrire '$da' ok; commit t2 $agent; git merge -q --no-ff --no-commit zz-cote; ecrire '$dc' 'k = \"$cle_aws\"'; commit m $agent --no-verify && $pousser"
attendu bloque "pre-push vers $P : feature sans verdict de gate" bash -c "$F; ecrire '$dedans' ok; commitf t $agent F-900 && $pousser"
attendu passe  "pre-push vers $P : gates APPROVED sur ce contenu" bash -c "$F; ecrire '$dedans' ok; commitf t $agent F-900 && $verdict && $pousser"
attendu bloque "pre-push vers $P : verdict périmé (code modifié après)" bash -c "$F; ecrire '$dedans' ok; commitf t $agent F-900 && $verdict && ecrire '$dedans' ok2 && commitf t2 $agent F-900 && $pousser"
attendu bloque "variable d'environnement : TEST_CMD=true ne neutralise pas les tests" bash -c "$F; ecrire '$rouge' x; TEST_CMD=true .agents/checks/verifier.sh --cle env"
attendu passe  "craft : verdict journalisé avec l'empreinte du dossier" bash -c "mkdir -p .agents/review/F-900 && printf 'CONTROLE format-lint: OK\nRESULTAT: OK\n' > .agents/review/F-900/checks.txt && echo e0e0e0e0e0e0 > .agents/review/F-900/empreinte && .agents/checks/craft.sh F-900 >/dev/null && tail -n 1 MEMORY/gates.log | grep -q '| e0e0e0e0e0e0\$'"
attendu bloque "outil de test absent => UNVERIFIED"             bash -c "$F; regle 'TEST_CMD=\"zz-runner-absent\"'; .agents/checks/verifier.sh --cle u1"
attendu passe  "outil de test absent, accepté hors CI par le dev" bash -c "$F; regle 'TEST_CMD=\"zz-runner-absent\"' 'ACCEPTE_UNVERIFIED_LOCAL=\"tests\"'; CI= .agents/checks/verifier.sh --cle u2"
attendu bloque "test qui sort en 4 (ex. pytest, erreur d'import) : FAIL, pas un UNVERIFIED acceptable" bash -c "$F; regle 'TEST_CMD=\"sh -c \\\"exit 4\\\"\"' 'TEST_REQUIERT=\"sh\"' 'ACCEPTE_UNVERIFIED_LOCAL=\"tests\"'; CI= .agents/checks/verifier.sh --cle u3"
attendu bloque "outil composé : binaire secondaire absent => UNVERIFIED" bash -c "$F; regle 'ZZ_CMD=\"true && zz-absent\"' 'ZZ_REQUIERT=\"true zz-absent\"'; . .agents/checks/lib.sh; outil ZZ"
attendu passe  "outil composé (deux chaînes d'outils) : s'exécute" bash -c "$F; regle 'ZZ_CMD=\"true && (cd . && true)\"'; . .agents/checks/lib.sh; outil ZZ"
attendu bloque "outil non configuré => UNVERIFIED"              bash -c '. .agents/checks/lib.sh; outil OUTIL_INEXISTANT'
[ -f .agents/perimetres/agent-planif.txt ] && \
attendu bloque "revue : spec modifiée après la validation du dev" bash -c "$F; ecrire specs/F-900.md 'Statut : validée'; commitf s agent-planif F-900 && ecrire '$dedans' ok && commitf t $agent F-900 && .agents/checks/dossier-revue.sh F-900"
[ -f .agents/perimetres/agent-planif.txt ] && \
attendu passe  "pre-push vers $P : planification seule (spec en brouillon), aucun gate exigé" bash -c "$F; ecrire specs/F-901.md 'Statut : brouillon'; printf 'Tier : standard\\n' >> specs/F-901.md; git add -A; commitf p agent-planif F-901 && $pousser"
"$py" -c 'import tomllib' >/dev/null 2>&1 && \
attendu bloque "deps : manifeste non géré modifié => UNVERIFIED" bash -c "$F; ecrire go.mod 'module exemple'; git commit -q -m g --trailer 'Agent: dev' && $py .agents/checks/deps-nouvelles.py $base"
attendu bloque "périmètre : « zzdir/*.py » ne couvre pas un sous-dossier" bash -c "printf 'zzdir/*.py\\n' > .agents/perimetres/zz-temoin.txt; .agents/checks/perimetre.sh --fichiers zz-temoin zzdir/sous/a.py"
attendu passe  "périmètre : « zzdir/*.py » couvre son dossier"    bash -c "printf 'zzdir/*.py\\n' > .agents/perimetres/zz-temoin.txt; .agents/checks/perimetre.sh --fichiers zz-temoin zzdir/a.py"
attendu passe  "critère cité en minuscules (f902_ac1) : couvert"  bash -c "mkdir -p zz-tests && echo 'def test_f902_ac1_x(): pass' > zz-tests/t.py && printf 'F-902-AC1\\n' > specs/F-902.md && .agents/checks/ac-couverture.sh F-902"
attendu bloque "critère sans test : refusé"                       bash -c "mkdir -p zz-tests && echo 'def test_autre(): pass' > zz-tests/t.py && printf 'F-903-AC1\\n' > specs/F-903.md && .agents/checks/ac-couverture.sh F-903"
attendu bloque "verdict lu en première ligne seulement (APPROVED cité plus loin)" bash -c "$F; regle 'GATE_CMD=\"sh $T/depot/zz-gate-ambigu.sh\"'; $revue_zz; .agents/checks/gate.sh reviewer-zz F-900; c=\$?; tail -n 1 MEMORY/gates.log | grep -q '| APPROVED |' && exit 0; exit \$c"
attendu passe  "reviewer qui répond UNVERIFIED : code 4, journalisé comme tel" bash -c "$F; regle 'GATE_CMD=\"cat >/dev/null; echo UNVERIFIED\"'; mkdir -p .agents/agents && printf -- '---\\nname: reviewer-zz\\n---\\nRevue.\\n' > .agents/agents/reviewer-zz.md; mkdir -p .agents/review/F-900 MEMORY && printf 'RESULTAT: OK\\n' > .agents/review/F-900/checks.txt && : > .agents/review/F-900/spec.md && : > .agents/review/F-900/diff.patch && echo e1e1e1e1e1e1 > .agents/review/F-900/empreinte; .agents/checks/gate.sh reviewer-zz F-900; [ \$? -eq 4 ] && tail -n 1 MEMORY/gates.log | grep -q 'contexte insuffisant'"
attendu bloque "projet existant : sync-agents n'écrase pas un CLAUDE.md écrit à la main" bash -c "printf 'règles maison\\n' > CLAUDE.md; .agents/checks/sync-agents.sh"
attendu bloque "périmètre : motif « /d/f » (idiome CODEOWNERS) protège bien (PROTEGE attendu)" bash -c "printf '\\n/%s\\n' '$dedans' >> .agents/perimetres/_protege.txt; .agents/checks/perimetre.sh --fichiers $agent '$dedans' 2>&1 | tee /dev/stderr | grep -q PROTEGE && exit 2; exit 0"
attendu bloque "périmètre : motif illisible pour CODEOWNERS (espace final) refusé" bash -c "printf '\\n.npmrc \\n' >> .agents/perimetres/_protege.txt; .agents/checks/perimetre.sh --fichiers $agent '$dedans'"
attendu bloque "périmètre : « d/* » ne couvre pas « d/sous/f » (comme CODEOWNERS)" bash -c "printf 'zzdir/*\\n' > .agents/perimetres/zz-temoin.txt; .agents/checks/perimetre.sh --fichiers zz-temoin zzdir/sous/f.txt"
attendu passe  "périmètre : « *.md » sans « / » vaut à toute profondeur" bash -c "printf '*.md\\n' > .agents/perimetres/zz-temoin.txt; .agents/checks/perimetre.sh --fichiers zz-temoin docs/sous/a.md"
attendu bloque "pre-push vers $P : code ajouté en résolvant un merge après le verdict (PÉRIMÉ)" bash -c "$F; ecrire '$da' ok; commitf t $agent F-900 && $verdict && git checkout -q -b zz-cote2 $base && ecrire '$db' ok && commit t2 $agent && git checkout -q - && git merge -q --no-ff --no-commit zz-cote2; ecrire '$dc' ajout; commit m $agent && $pousser"
attendu bloque "pre-push vers $P : code ajouté dans un merge inversé (feature fusionnée dans une copie de $P) après le verdict" bash -c "$F; b=\$(git symbolic-ref --short HEAD); ecrire '$da' ok; commitf t $agent F-900 && $verdict && git checkout -q -b zz-inv $base && ecrire '$db' ok && commit t2 $agent && git merge -q --no-ff --no-commit \$b; ecrire '$dc' ajout; commit m $agent && git checkout -q \$b && git reset -q --hard zz-inv && $pousser"
attendu bloque "pre-push vers $P : code « Feature: trivial » ajouté après le verdict (PÉRIMÉ)" bash -c "$F; ecrire '$da' ok; commitf t $agent F-900 && $verdict && ecrire '$db' ajout && commit t2 $agent && $pousser"
attendu bloque "pre-push : commit d'agent sans trailer Feature (--no-verify)" bash -c "$F; ecrire '$dedans' ok; git commit -q -m t --trailer 'Agent: $agent' --no-verify && $pousser"
attendu bloque "pre-commit : secret exempté par un commentaire gitleaks:allow" bash -c "$F; ecrire '$dedans' 'k = \"$cle_aws\" // gitleaks:allow'; commit t $agent"
attendu bloque "pre-push vers $P : merge d'agent dont la résolution est le seul code de la feature (gate exigé)" bash -c "$F; git checkout -q -b zz-m1 $base && ecrire '$db' ok && commit t2 $agent && git checkout -q - && git merge -q --no-ff --no-commit zz-m1; ecrire '$dc' ajout; commitf m $agent F-900 && $pousser"
attendu bloque "pre-push : commit à deux trailers Feature (--no-verify)" bash -c "$F; ecrire '$dedans' ok; git commit -q -m t --trailer 'Agent: $agent' --trailer 'Feature: F-900' --trailer 'Feature: trivial' --no-verify && $pousser"
attendu bloque "pre-push vers $P : spec combinée par un merge propre avec une retouche non validée" bash -c "$F; ecrire '$da' ok; commitf t $agent F-900 && git checkout -q -b zz-sp $base && sed -i.bak 's/^Tier : standard/Tier : trivial/' specs/F-900.md && rm -f specs/F-900.md.bak && git add -A && commit s agent-planif && git checkout -q - && printf -- '- F-900-AC2 : x.\\n' >> specs/F-900.md && git add -A && git commit -q -m v --trailer 'Agent: dev' && git merge -q --no-ff --no-edit zz-sp && $pousser"
attendu bloque "pre-push : merge à trois parents (octopus) refusé" bash -c "$F; git checkout -q -b zz-o1 $base && ecrire '$da' ok && commit a $agent && git checkout -q -b zz-o2 $base && ecrire '$db' ok && commit b $agent && git checkout -q - && git checkout -q -b zz-o3 $base && git merge -q --no-ff --no-edit zz-o1 zz-o2 && $pousser"
attendu bloque "pre-push : trailer « Feature: * » (valeur invalide, --no-verify)" bash -c "$F; ecrire '$dedans' ok; git commit -q -m t --trailer 'Agent: $agent' --trailer 'Feature: *' --no-verify && $pousser"
attendu passe  "planification seulement : un chemin contenant « a/specs/ » reste du contenu" bash -c "$F; ecrire 'zz a/specs/r.txt' ok; git commit -q -m t --trailer 'Agent: dev' --trailer 'Feature: F-900' && . .agents/checks/lib.sh && a_du_contenu F-900 origin/$P..HEAD"
attendu passe  "empreinte d'un merge résolu à la main : indépendante de core.abbrev" bash -c "$F; ecrire '$da' ok; commitf t $agent F-900 && git checkout -q -b zz-ab $base && ecrire '$da' autre && commit t2 $agent && git checkout -q - && { git merge -q --no-commit zz-ab >/dev/null 2>&1; ecrire '$da' 'ok autre'; commit m $agent; } && e1=\$(bash -c '. .agents/checks/lib.sh; empreinte_feature F-900 origin/$P..HEAD') && e2=\$(GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.abbrev GIT_CONFIG_VALUE_0=12 bash -c '. .agents/checks/lib.sh; empreinte_feature F-900 origin/$P..HEAD') && echo \"\$e1 \$e2\" && [ \"\$e1\" = \"\$e2\" ]"
attendu bloque "pre-push vers $P : code réécrit après le verdict, seuls les blancs changent (PÉRIMÉ)" bash -c "$F; ecrire '$da' 'rm -rf /tmp/c'; commitf t $agent F-900 && e=\$(bash -c '. .agents/checks/lib.sh; empreinte_feature F-900 origin/$P..HEAD') && git reset -q --hard $base && ecrire '$da' 'rm -rf / tmp/c' && commitf t $agent F-900 && mkdir -p MEMORY && echo \"2026-01-01T00:00:00Z | zz-gate-temoin | F-900 | APPROVED | \$e\" >> MEMORY/gates.log && git add -A && commitf journal $agent F-900 && $pousser"
attendu passe  "empreinte indépendante de la configuration git du poste (diff.noprefix, diff.context)" bash -c "$F; ecrire '$da' ok; commitf t $agent F-900 && e1=\$(bash -c '. .agents/checks/lib.sh; empreinte_feature F-900 origin/$P..HEAD') && e2=\$(GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=diff.noprefix GIT_CONFIG_VALUE_0=true GIT_CONFIG_KEY_1=diff.context GIT_CONFIG_VALUE_1=8 bash -c '. .agents/checks/lib.sh; empreinte_feature F-900 origin/$P..HEAD') && echo \"\$e1 \$e2\" && [ \"\$e1\" = \"\$e2\" ]"
attendu bloque "commit-msg : un dossier nommé PROJECT_LOG.md n'est pas de la traçabilité" bash -c "$F; ecrire PROJECT_LOG.md/zz.test.mjs ok; commitf t $agent F-900"
attendu passe  "dossier de revue : un fichier avec un octet NUL reste lisible par les gates" bash -c "$F; mkdir -p \"\$(dirname '$da')\" && printf 'a\\000b role=zzadmin\\n' > '$da' && git add -A && commitf t $agent F-900 && { .agents/checks/dossier-revue.sh F-900 >/dev/null 2>&1; grep -aq 'role=zzadmin' .agents/review/F-900/diff.patch; }"
attendu bloque "pre-push vers $P : spec validée en « Tier : trivial » refusée (un trivial n'a pas de spec)" bash -c "$F; sed -i.bak 's/^Tier : standard/Tier : trivial/' specs/F-900.md && rm -f specs/F-900.md.bak && git add -A && git commit -q -m v --trailer 'Agent: dev' && ecrire '$da' ok && commitf t $agent F-900 && $pousser"
attendu passe  "pre-push vers $P : merge sans résolution manuelle, verdict toujours valable" bash -c "$F; ecrire '$da' ok; commitf t $agent F-900 && $verdict && git checkout -q -b zz-cote3 $base && ecrire '$db' ok && commit t2 $agent && git checkout -q - && git merge -q --no-ff --no-edit zz-cote3 && $pousser"
attendu bloque "pre-push vers $P : spec retouchée après validation (Tier : trivial) => refusée" bash -c "$F; ecrire '$da' ok; commitf t $agent F-900 && sed -i.bak 's/^Tier : standard/Tier : trivial/' specs/F-900.md && rm -f specs/F-900.md.bak && git add -A && commit s agent-planif && $pousser"
attendu bloque "pre-push vers $P : verdict écrit mais non commité, ne compte pas" bash -c "$F; ecrire '$da' ok; commitf t $agent F-900 && e=\$(bash -c '. .agents/checks/lib.sh; empreinte_feature F-900 origin/$P..HEAD') && mkdir -p MEMORY && echo \"2026-01-01T00:00:00Z | zz-gate-temoin | F-900 | APPROVED | \$e\" >> MEMORY/gates.log && $pousser"
attendu bloque "périmètre : « ** » qui n'est pas un segment entier refusé (« zzdir/**.py »)" bash -c "printf 'zzdir/**.py\\n' > .agents/perimetres/zz-temoin.txt; .agents/checks/perimetre.sh --fichiers zz-temoin zzdir/a.py"
attendu bloque "périmètre : « .zzconf* » protège aussi le contenu du dossier .zzconf/ (PROTEGE attendu)" bash -c "printf '\\n.zzconf*\\n' >> .agents/perimetres/_protege.txt; .agents/checks/perimetre.sh --fichiers $agent .zzconf/r.yml 2>&1 | tee /dev/stderr | grep -q PROTEGE && exit 2; exit 0"
attendu bloque "gabarit de verdict recopié (« APPROVED / CHANGES_REQUESTED ») : pas un verdict" bash -c "$F; regle 'GATE_CMD=\"cat >/dev/null; echo APPROVED / CHANGES_REQUESTED\"'; $revue_zz; .agents/checks/gate.sh reviewer-zz F-900; c=\$?; tail -n 1 MEMORY/gates.log | grep -q '| APPROVED |' && exit 0; exit \$c"
attendu passe  "journal des gates : deux branches fusionnent sans conflit (.gitattributes : merge=union)" bash -c "$F; git checkout -q -b zz-j1 && mkdir -p MEMORY && echo j1 >> MEMORY/gates.log && git add -A && commit j1 $agent && git checkout -q - && mkdir -p MEMORY && echo j2 >> MEMORY/gates.log && git add -A && commit j2 $agent && git merge -q --no-edit zz-j1"
attendu bloque "CI : base introuvable (clone partiel)"           .agents/checks/perimetre.sh --commits origin/inexistante..HEAD
attendu bloque "gate : arbre modifié pendant la revue"           bash -c ".agents/checks/lecture-seule.sh debut t && echo x >> zz-gate-temoin.txt && .agents/checks/lecture-seule.sh fin t"
attendu passe  "changement conforme : commit + push"             bash -c "$F; ecrire '$dedans' ok; commit t $agent && $pousser"

if [ -x .claude/hooks/cc-adapt.sh ] && command -v jq >/dev/null 2>&1; then
  echo "== 3. Adaptateur Claude Code (entrées JSON conformes à la doc)"
  export CLAUDE_PROJECT_DIR="$PWD"; a=.claude/hooks/cc-adapt.sh
  attendu bloque "Claude Code : écriture hors périmètre (sous-agent)" bash -c "echo '{\"agent_type\":\"$agent\",\"tool_input\":{\"file_path\":\"$PWD/zz.txt\"}}' | $a perimetre"
  attendu bloque "Claude Code : sous-agent sans périmètre"            bash -c "echo '{\"agent_type\":\"general-purpose\",\"tool_input\":{\"file_path\":\"$PWD/$dedans\"}}' | $a perimetre"
  attendu bloque "Claude Code : conversation principale écrit du code" bash -c "echo '{\"tool_input\":{\"file_path\":\"$PWD/$dedans\"}}' | $a perimetre"
  attendu bloque "Claude Code : chemin avec .."                       bash -c "echo '{\"agent_type\":\"$agent\",\"tool_input\":{\"file_path\":\"$PWD/$dedans/../../zz.txt\"}}' | $a perimetre"
  attendu passe  "Claude Code : écriture dans le périmètre"           bash -c "echo '{\"agent_type\":\"$agent\",\"tool_input\":{\"file_path\":\"$PWD/$dedans\"}}' | $a perimetre"
  attendu passe  "Claude Code : projet ouvert par un lien symbolique" bash -c "ln -sfn '$PWD' '$T/lien' && echo '{\"agent_type\":\"$agent\",\"tool_input\":{\"file_path\":\"$T/lien/$dedans\"}}' | $a perimetre"
  attendu bloque "Claude Code : fin de tour avec test rouge"          bash -c "$F; ecrire '$rouge' x; echo '{\"session_id\":\"t\"}' | $a verifier"
  attendu passe  "Claude Code (route B) : reviewer « UNVERIFIED » qui cite APPROVED plus loin, journalisé UNVERIFIED" bash -c "echo '{\"agent_type\":\"reviewer-zz\"}' | $a gate-debut && echo '{\"agent_type\":\"reviewer-zz\",\"last_assistant_message\":\"UNVERIFIED\\nimpossible de conclure APPROVED sans les appelants\"}' | $a gate-fin && tail -n 1 MEMORY/gates.log | grep -q '| reviewer-zz | .* | UNVERIFIED (contexte insuffisant'"
  attendu bloque "Claude Code : mode inconnu"                         bash -c "echo '{}' | $a zz-mode-inconnu"
fi
[ $ko -eq 0 ] && { echo "RESULTAT: tous les blocages sont effectifs"; exit 0; }
echo "RESULTAT: au moins un contrôle ne bloque pas, ou un outil est introuvable"; exit 2
