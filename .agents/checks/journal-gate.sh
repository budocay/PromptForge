#!/bin/bash
# Usage : journal-gate.sh <agent> [F-id] [empreinte] < rapport — une ligne par passage de gate (§6.2) :
#   date | agent | F-id | verdict | empreinte du contenu jugé (lue par gates-verts.sh)
# Sans F-id (route B, appel par l'adaptateur) : feature et empreinte du dernier dossier de revue construit.
# Rapport marqué « NON INDÉPENDANTE » (mode dégradé, §3.0) en prod pour sécurité/architecture : UNVERIFIED.
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
fid="${2:-}"; emp="${3:-}"
if [ -f .agents/.state/dossier-courant ]; then
  read -r dfid demp < .agents/.state/dossier-courant
  [ -n "$fid" ] || fid="$dfid"
  [ -n "$emp" ] || { [ "$fid" = "$dfid" ] && emp="$demp"; }
fi
rapport="$(cat)"
v="$(printf '%s\n' "$rapport" | verdict_de "${1:-}")"
if printf '%s' "$rapport" | grep -q 'NON INDÉPENDANTE' && [ "${CRITICITE:-prod}" = prod ]; then
  case "${1:-}" in agent-securite|agent-architecte) v="UNVERIFIED (NON INDÉPENDANTE, prod)" ;; esac
fi
mkdir -p MEMORY
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) | ${1:-?} | ${fid:--} | ${v:-verdict absent} | ${emp:--}" >> MEMORY/gates.log
