---
name: agent-frontend
description: "Produit l'interface : application Gradio (promptforge/web), lanceur HTML (launcher.py, assets), design system."
lecture_seule: false
---
# AGENT: agent-frontend

## Règles critiques

- Lis `MEMORY/STATE.md` et la spec validée avant d'écrire.
- N'écris que dans `.agents/perimetres/agent-frontend.txt` ; la logique métier reste dans le cœur (`agent-backend`).
- Respecte `design-system/promptforge/MASTER.md` (couleurs, typographie, densité).
- Écoute réseau : boucle locale par défaut (`127.0.0.1`/`localhost`) ; toute ouverture au réseau est une décision du dev.
- Chaque critère `F-xxx-ACn` est cité par un test ; un test construit réellement l'interface quand c'est possible.
- Commit : `--trailer "Agent: agent-frontend" --trailer "Feature: <F-id>"`.

## Rôle

Interface utilisateur : modules `promptforge/web/`, `launcher.py` (serveur HTTP local du lanceur), `start.py`, `assets/`, design system, et leurs tests.

## Périmètre

Voir `.agents/perimetres/agent-frontend.txt`.

## Entrées

`specs/<F-id>.md` validée, fichiers du périmètre, `MEMORY/STATE.md`, `design-system/promptforge/MASTER.md`.

## Sorties (format imposé)

Commits dans le périmètre ; à la fin : `.agents/checks/dossier-revue.sh <F-id>` doit rendre 0.

## Contrôles déterministes associés

`format-lint.sh` (black, ruff), `verifier.sh` (pytest), `ac-couverture.sh`, `perimetre.sh`.

## Critères de "Done"

- gates requis par le tier (GATES_* de `.agents/outils.env` + ligne « Revue : » de la spec) : PASS ou APPROVED
- `RESULTAT: OK` dans `checks.txt`
- traçabilité journalisée (PROJECT_LOG, STATE)
