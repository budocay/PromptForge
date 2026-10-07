# STATE — PromptForge — 2026-10-07

## Où on en est

AGENT_FACTORY 2.3.0-rc.1 appliqué (branche `agent-factory`). Historique antérieur : F-001 à F-032, D-001 à D-068, DEC-001 à DEC-012, non repris (pas de PROJECT_LOG importé). Aucune feature en cours.

## Prochaine action prévue

Le dev valide la spec `specs/F-033.md` (exposition réseau), puis `agent-frontend` la réalise (tier standard).

## Dettes ouvertes

- D-069 Sept constats bandit existants figés dans `.bandit-baseline.json` (urlopen sur URL configurable ×5, `shell=True` sous Windows dans `utils.py`, écoute `0.0.0.0` par défaut de `launch_web`) — depuis la génération — impact : relus au cas par cas, le dernier traité par F-033.
- D-070 Pas de contrat de dépendances exécutable (le cœur ne doit pas importer `promptforge.web`) — proposer import-linter.

## État des contrôles / gates

Socle extrait et vérifié (`.agents/SOCLE.sha256`) ; `test-blocage.sh` : voir le dernier passage. Aucun verdict de gate.

## Pièges actifs

- Les contrôles exigent `.venv` à la racine du dépôt (voir AGENTS.md).
