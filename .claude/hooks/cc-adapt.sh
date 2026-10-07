#!/bin/bash
# Adaptateur Claude Code -> socle (§4.3). Traduit l'entrée JSON du hook et les codes de sortie ; aucune règle ici.
# Claude Code : seul le code 2 bloque ; Stop/SubagentStop en code 2 font continuer le modèle avec stderr.
command -v jq >/dev/null 2>&1 || { echo "cc-adapt : jq introuvable, écriture bloquée (échec fermé)" >&2; exit 2; }
input="$(cat)"; C="$CLAUDE_PROJECT_DIR/.agents/checks"
j() { jq -r "$1 // empty" <<<"$input"; }
case "$1" in
  perimetre)       # PreToolUse Edit|Write|NotebookEdit
    f="$(j '.tool_input.file_path // .tool_input.notebook_path')"; [ -n "$f" ] || exit 0
    agent="$(j .agent_type)"; agent="${agent:-orchestrateur}"   # conversation principale = orchestrateur
    "$C/perimetre.sh" --fichiers "$agent" "$f" || exit 2 ;;    # agent sans périmètre => bloqué aussi
  format-lint)     # PostToolUse Edit|Write (ne peut pas bloquer : retour au modèle)
    f="$(j .tool_input.file_path)"; [ -n "$f" ] || exit 0
    "$C/format-lint.sh" "$f" || exit 2 ;;
  verifier)        # Stop, SubagentStop des producteurs
    cd "$CLAUDE_PROJECT_DIR" || exit 2
    [ -z "$(git status --porcelain -- . ':!MEMORY')" ] && exit 0
    "$C/verifier.sh" --cle "$(j .session_id)"; code=$?
    case $code in
      0) exit 0 ;;
      3) jq -nc '{continue: false, stopReason: "ESCALADE (§5.6) : 3 échecs consécutifs des contrôles."}'; exit 0 ;;
      *) exit 2 ;;
    esac ;;
  gate-debut)      # SubagentStart des gates (route sous-agent, §3.0)
    "$C/lecture-seule.sh" debut "$(j .agent_type)" || exit 2 ;;
  gate-fin)        # SubagentStop des gates : arbre inchangé, puis journal
    if "$C/lecture-seule.sh" fin "$(j .agent_type)"; then
      j .last_assistant_message | "$C/journal-gate.sh" "$(j .agent_type)"
    else
      echo "INVALIDE (arbre modifié)" | "$C/journal-gate.sh" "$(j .agent_type)"
    fi ;;
  *) echo "cc-adapt : mode inconnu '$1'" >&2; exit 2 ;;
esac
exit 0
