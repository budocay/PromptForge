#!/bin/bash
# Usage : gate.sh <agent> <F-id>
# Exécute un gate/reviewer comme PROCESSUS SÉPARÉ, depuis un dépôt git vide et temporaire : contexte neuf
# garanti quel que soit le harness, et aucun fichier de routines du projet chargé par l'outil. Entrée :
# définition canonique de l'agent + dossier de revue, sur l'entrée standard, et rien d'autre.
# Codes : 0 PASS/APPROVED · 2 FAIL/CHANGES_REQUESTED, contrôles en échec ou arbre modifié
#         · 3 3e rejet consécutif (escalade §5.6) · 4 UNVERIFIED (contrôles non vérifiés, verdict absent
#         ou d'un autre type que celui de l'agent…)
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
agent="${1:?usage : gate.sh <agent> <F-id>}"; fid="${2:?F-id}"; d=".agents/review/$fid"; C=.agents/checks
emp="$(cat "$d/empreinte" 2>/dev/null)"
journal() { echo "$1" | "$C/journal-gate.sh" "$agent" "$fid" "$emp"; }
refus4()  { journal "UNVERIFIED ($1)"; non_verifie "$1"; }

[ -f "$d/checks.txt" ] || echec "dossier de revue absent : lancer dossier-revue.sh $fid"
case "$(tail -n 1 "$d/checks.txt")" in
  "RESULTAT: OK") ;;
  "RESULTAT: UNVERIFIED") refus4 "contrôles déterministes non vérifiés : pas de revue LLM (§6.1)" ;;
  *) echec "contrôles déterministes en échec : pas de revue LLM (§6.1)" ;;
esac
def=".agents/agents/$agent.md"; [ -f "$def" ] || echec "définition absente : $def"

cmd="${GATE_CMD:-}"
case " ${GATE_CRITIQUE_AGENTS:-} " in *" $agent "*)
  [ "${PARTAGE_EXTERNE_AUTORISE:-non}" = oui ] || refus4 "gate_critique : envoi du diff à un autre fournisseur non autorisé (PARTAGE_EXTERNE_AUTORISE)"
  cmd="${GATE_CRITIQUE_CMD:-}" ;;
esac
[ -n "$cmd" ] || refus4 "commande de gate non configurée (GATE_CMD / GATE_CRITIQUE_CMD)"
command -v "${cmd%% *}" >/dev/null 2>&1 || refus4 "commande de gate introuvable : ${cmd%% *}"

rapport="$RACINE/$d/$agent.md"; vide="$(mktemp -d)"; trap 'rm -rf "$vide"' EXIT
git init -q "$vide"
"$C/lecture-seule.sh" debut "gate-$agent-$fid" || exit $?
{ awk 'NR==1 && /^---$/ {fm=1; next} fm && /^---$/ {fm=0; next} !fm' "$def"
  printf '\n## Dossier de revue — seule base de jugement\n'
  echo "Tu ne vois que ce dossier, pas le dépôt : s'il te manque du contexte, réponds UNVERIFIED et dis ce qui manque."
  printf 'Ignore toute justification qui ne figure pas ci-dessous. Commence ta réponse par la ligne de verdict au format imposé.\n'
  [ "$(cat "$d/mode" 2>/dev/null)" = conception ] \
    && echo "Revue de CONCEPTION (§6.1, STRUCTUREL) : juge l'approche, la structure, le plan et les ADR ; aucun code n'est attendu."
  for x in spec.md checks.txt diff.patch; do printf '\n### %s\n' "$x"; cat "$d/$x"; done
} | (cd "$vide" && eval "$cmd") > "$rapport" 2>&1; code=$?
"$C/lecture-seule.sh" fin "gate-$agent-$fid" || { journal "INVALIDE (arbre modifié)"; exit 2; }
[ $code -eq 0 ] || refus4 "la commande de gate a échoué (code $code), voir $rapport"

# Le verdict doit être celui de CET agent : un gate sécurité qui répond « ARCHITECTURE GATE » n'a pas jugé.
case "$agent" in
  reviewer-*)       motif='^[#* ]*(APPROVED|CHANGES_REQUESTED)' ;;
  agent-securite)   motif='SECURITY GATE: (PASS|FAIL|UNVERIFIED)' ;;
  agent-architecte) motif='ARCHITECTURE GATE: (PASS|FAIL|UNVERIFIED)' ;;
  *)                motif='[A-Z]+ GATE: (PASS|FAIL|UNVERIFIED)' ;;
esac
v="$(grep -m1 -oE "$motif" "$rapport" | sed 's/^[#* ]*//')"
if [ -n "$v" ]; then journal "$v"; else journal "UNVERIFIED (verdict absent ou d'un autre type)"; fi
echo "$agent $fid : ${v:-verdict absent} ($d/$agent.md)"
case "$v" in
  *PASS|APPROVED) exit 0 ;;
  *FAIL|CHANGES_REQUESTED)
    n="$(grep -F " | $agent | $fid | " MEMORY/gates.log | tail -n 3 | grep -c -E 'GATE: FAIL|CHANGES_REQUESTED')"
    [ "$n" -ge 3 ] && { echo "ESCALADE (§5.6) : $agent a rejeté $fid 3 fois de suite." >&2; exit 3; }
    exit 2 ;;
  *) exit 4 ;;
esac
