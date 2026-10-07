# STATE — PromptForge — 2026-10-07

## Où on en est

F-033 (standard, écoute réseau sur la boucle locale) codée et revue sur `feat/F-033` : sécurité PASS, reviewer-frontend APPROVED, craft PASS, architecture UNVERIFIED (empreinte 8b270c05accb). DONE sous réserve du point Windows ci-dessous.

## Prochaine action prévue

Le dev vérifie sous Windows (lanceur + Docker Desktop, compose win-amd ou win-nvidia) que l'interface joint Ollama natif lancé avec `OLLAMA_HOST=127.0.0.1:11434`. Concluant : ligne `DEROGATION D-071` du dev pour agent-architecte dans `MEMORY/gates.log`, puis fusion. Négatif : reprendre la spec (AC2/AC3).

## Dettes ouvertes

- D-071 Chemin Windows « conteneur → Ollama natif » non vérifié avec Ollama sur 127.0.0.1 (host.docker.internal) — depuis F-033 — impact : l'interface dockerisée pourrait ne plus joindre Ollama sous Windows.
- D-069 Sept constats bandit existants figés dans `.bandit-baseline.json` (urlopen sur URL configurable ×5, `shell=True` sous Windows dans `utils.py`, écoute `0.0.0.0` par défaut de `launch_web`, corrigé par F-033 : base de référence à régénérer par le dev) — depuis la génération — impact : relus au cas par cas.
- D-070 Pas de contrat de dépendances exécutable (le cœur ne doit pas importer `promptforge.web`) — proposer import-linter.

## État des contrôles / gates

Socle extrait et vérifié ; `test-blocage.sh` 42/42 ; CI verte sur main. F-033 : `dossier-revue.sh` OK ; architecte UNVERIFIED (D-071), autres gates verts.

## Pièges actifs

- Les contrôles exigent `.venv` à la racine du dépôt (voir AGENTS.md).
