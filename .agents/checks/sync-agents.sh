#!/bin/bash
# Usage : sync-agents.sh [--check]
# Projette ce qui est canonique vers chaque harness de $HARNESS (outils.env) :
#   .agents/agents/<id>.md  -> .claude/agents/<id>.md · .cursor/agents/<id>.md · .codex/agents/<id>.toml
#   .agents/skills/         -> .claude/skills/ (Codex et Cursor lisent .agents/skills/ nativement)
#   AGENTS.md               -> CLAUDE.md (« @AGENTS.md »)
#   _protege + _partage     -> CODEOWNERS (si CODEOWNER est défini), plus specs/ et MEMORY/gates.log
# Les fichiers projetés ne s'éditent jamais à la main ; --check échoue s'ils divergent ou sont orphelins.
# Frontmatter canonique (plat, une clé par ligne) : name, description, lecture_seule (true|false),
#   modele_claude_code, modele_cursor, modele_codex (optionnels), modele_externe (true si l'un de ces
#   modèles est d'un autre fournisseur que celui du projet : exige PARTAGE_EXTERNE_AUTORISE="oui").
# Formats vérifiés dans la doc de chaque éditeur le 2026-10-07 (annexe C).
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
check=0; [ "${1:-}" = --check ] && check=1
sortie="$RACINE"; [ $check -eq 1 ] && { sortie="$(mktemp -d)"; trap 'rm -rf "$sortie"' EXIT; }
GEN="généré par .agents/checks/sync-agents.sh : ne pas éditer"

champ() { # champ <fichier> <clé> : valeur sans commentaire « # … » final ni guillemets englobants
  awk -v k="$2" '
    NR==1 && /^---$/ {fm=1; next}
    fm && /^---$/ {exit}
    fm { i=index($0,":"); if (substr($0,1,i-1)!=k) next
         v=substr($0,i+1); sub(/[ \t]+#.*$/,"",v); sub(/^[ \t]+/,"",v); sub(/[ \t]+$/,"",v)
         if (v ~ /^".*"$/ || v ~ /^\047.*\047$/) v=substr(v,2,length(v)-2)
         print v; exit }' "$1"
}
corps() { awk 'NR==1&&/^---$/{fm=1;next} fm&&/^---$/{fm=0;next} !fm' "$1"; }
yq()    { printf '"%s"' "$(printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g')"; }   # chaîne YAML/TOML entre guillemets

attendus=""
for def in .agents/agents/*.md; do
  [ -f "$def" ] || continue
  nom="$(champ "$def" name)"; desc="$(champ "$def" description)"; ro="$(champ "$def" lecture_seule)"
  printf '%s' "$nom" | grep -qE '^[a-z0-9][a-z0-9-]*$' || echec "$def : name invalide ('$nom')"
  [ -n "$desc" ] || echec "$def : description obligatoire"
  case "$ro" in true|false) ;; *) echec "$def : lecture_seule doit valoir true ou false ('$ro')" ;; esac
  if [ "$(champ "$def" modele_externe)" = true ] && [ "${PARTAGE_EXTERNE_AUTORISE:-non}" != oui ]; then
    echec "$def : modèle d'un autre fournisseur sans PARTAGE_EXTERNE_AUTORISE=\"oui\" (§3.0)"
  fi
  for h in ${HARNESS:-}; do
    case "$h" in
      claude-code) f=".claude/agents/$nom.md"; m="$(champ "$def" modele_claude_code)"
        mkdir -p "$sortie/.claude/agents"
        { echo "---"; echo "# $GEN"; echo "name: $nom"; echo "description: $(yq "$desc")"
          [ "$ro" = true ] && echo "tools: Read, Grep, Glob"
          [ -n "$m" ] && echo "model: $(yq "$m")"
          echo "---"; corps "$def"; } > "$sortie/$f" ;;
      cursor) f=".cursor/agents/$nom.md"; m="$(champ "$def" modele_cursor)"
        mkdir -p "$sortie/.cursor/agents"
        { echo "---"; echo "# $GEN"; echo "name: $nom"; echo "description: $(yq "$desc")"
          [ -n "$m" ] && echo "model: $(yq "$m")"
          echo "readonly: $ro"
          echo "---"; corps "$def"; } > "$sortie/$f" ;;
      codex) f=".codex/agents/$nom.toml"; m="$(champ "$def" modele_codex)"
        corps "$def" | grep -q "'''" && echec "$def : le corps contient ''' (incompatible avec une chaîne TOML littérale)"
        mkdir -p "$sortie/.codex/agents"
        { echo "# $GEN"; echo "name = $(yq "$nom")"; echo "description = $(yq "$desc")"
          [ -n "$m" ] && echo "model = $(yq "$m")"
          [ "$ro" = true ] && echo 'sandbox_mode = "read-only"'
          echo "developer_instructions = '''"; corps "$def"; echo "'''"; } > "$sortie/$f" ;;
      *) echec "harness inconnu dans HARNESS : $h (ajouter sa projection après vérification de sa doc, §4.3)" ;;
    esac
    attendus="$attendus $f"
  done
done

case " ${HARNESS:-} " in *" claude-code "*)
  printf '%s\n' "<!-- $GEN -->" "@AGENTS.md" > "$sortie/CLAUDE.md"; attendus="$attendus CLAUDE.md"
  if [ -d .agents/skills ]; then
    rm -rf "$sortie/.claude/skills"; mkdir -p "$sortie/.claude"; cp -R .agents/skills "$sortie/.claude/skills"
    attendus="$attendus .claude/skills"
  fi ;;
esac

if [ -n "${CODEOWNER:-}" ]; then
  { echo "# $GEN — depuis .agents/perimetres/_protege.txt et _partage.txt"
    cat .agents/perimetres/_protege.txt .agents/perimetres/_partage.txt 2>/dev/null \
      | grep -v -e '^#' -e '^[[:space:]]*$' | while IFS= read -r g; do
          case "$g" in /*|\*\**) echo "$g $CODEOWNER" ;; *) echo "/$g $CODEOWNER" ;; esac
        done
    echo "/specs/ $CODEOWNER"              # contrat validé par le dev (§6.0)
    echo "/MEMORY/gates.log $CODEOWNER"; } > "$sortie/CODEOWNERS"   # journal lu par gates-verts.sh
  attendus="$attendus CODEOWNERS"
fi

[ $check -eq 1 ] || { echo "Projections à jour (HARNESS : ${HARNESS:-aucun})"; exit 0; }
rc=0
for f in $attendus; do
  if [ -d "$sortie/$f" ]; then diff -rq "$sortie/$f" "$RACINE/$f" >/dev/null 2>&1 || { echo "DÉRIVE : $f (lancer sync-agents.sh)" >&2; rc=2; }
  else cmp -s "$sortie/$f" "$RACINE/$f" || { echo "DÉRIVE : $f diffère de la projection (lancer sync-agents.sh)" >&2; rc=2; }
  fi
done
for dir in .claude/agents .cursor/agents .codex/agents; do
  [ -d "$RACINE/$dir" ] || continue
  for f in "$RACINE/$dir"/*; do
    [ -f "$f" ] || continue; r="${f#"$RACINE"/}"
    case " $attendus " in *" $r "*) ;; *) echo "ORPHELIN : $r sans définition canonique" >&2; rc=2 ;; esac
  done
done
exit $rc
