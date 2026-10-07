#!/bin/bash
# Usage : craft.sh <F-id>
# Assemble le CRAFT GATE (§3.6) sans passe LLM : verdict = contrôle format-lint de checks.txt ;
# suggestions = sections « Suggestions craft » des rapports de reviewers. Écrit craft.md et journalise.
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
fid="${1:?usage : craft.sh <F-id>}"; d=".agents/review/$fid"
[ -f "$d/checks.txt" ] || echec "dossier de revue absent : lancer dossier-revue.sh $fid"
etat="$(sed -n 's/^CONTROLE format-lint: //p' "$d/checks.txt" | head -n 1)"
case "$etat" in
  ""|OK)         v=PASS ;;                 # aucun fichier concerné, ou contrôle vert
  UNVERIFIED*)   v=UNVERIFIED ;;
  *)             v=FAIL ;;
esac
{ echo "CRAFT GATE: $v"
  echo "- Contrôles déterministes (checks.txt) : format-lint ${etat:-sans fichier concerné}"
  echo "- Suggestions (non bloquantes, issues de la revue) :"
  for r in "$d"/reviewer-*.md; do
    [ -f "$r" ] && awk '/^#+ *Suggestions craft/{on=1; next} /^#+ /{on=0} on' "$r" | sed 's/^/  /'
  done
} > "$d/craft.md"
"$(dirname "$0")/journal-gate.sh" agent-craft "$fid" "$(cat "$d/empreinte" 2>/dev/null)" < "$d/craft.md"
cat "$d/craft.md"
case "$v" in PASS) exit 0 ;; UNVERIFIED) exit 4 ;; *) exit 2 ;; esac
