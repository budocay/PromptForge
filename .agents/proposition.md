# Agents proposés pour PromptForge

| Agent | Rôle | Pourquoi (réf. §1) | Reviewer | Périmètre | Modèle |
|-------|------|--------------------|----------|-----------|--------|
| agent-backend | cœur Python, providers, scanner, sécurité, SQLite, CLI | `backend`, `base_de_donnees` (fusionné : un seul module SQLite) | reviewer-backend (+ checklist BDD) | `promptforge/*.py` listés, `scanner/**`, `templates/**`, tests du cœur | hérité |
| agent-frontend | interface Gradio, lanceur, assets, design system | `frontend` | reviewer-frontend | `promptforge/web/**`, `launcher.py`, `start.py`, `assets/**`, `design-system/**`, tests web | hérité |
| agent-devops | Docker, compose, Makefile, build | `infra`, `ci_cd`, `packaging` | reviewer-devops | `docker/**`, `compose.yaml`, `Makefile`, scripts de build, guide Docker | hérité |

Agents structurels (non négociables) : agent-planif, agent-securite, agent-architecte,
agent-architecte-conception, agent-craft, agent-veille.
Conversation principale : orchestrateur (délègue ; périmètre : orchestrateur.txt, vide)
Gates requis par tier (outils.env) : GATES_STANDARD=agent-architecte agent-securite agent-craft · GATES_STRUCTUREL=idem ; reviewers : ligne « Revue : » de chaque spec
Harness ciblés et projections (§4.1) : claude-code
Contrôles par moment (§2.3, §4.2) : écriture oui (Claude Code) · commit · push · merge (controles + gates-verts, CODEOWNERS @budocay)
Indépendance des gates (§3.0) : processus séparé (gate.sh, `claude -p`)
Modes dégradés actifs : aucun
Hypothèses prises sans confirmation :
- H1 `agent-bdd` fusionné dans `agent-backend` : la base tient dans `database.py` ; un agent de plus pour un module serait du bruit (§3.5, juste dimensionnement).
- H2 Outils pris dans `.venv` à la racine (chemins absolus via `$RACINE`) : convention de CONTRIBUTING.md, et PATH du harness non garanti.
- H3 SAST = bandit avec base de référence (7 constats existants → dette D-069) ; SCA = pip-audit (réseau requis). Ajout de `bandit` et `pip-audit` à l'environnement de dev à décider par le dev (`pyproject.toml`, partagé).
- H4 Fichiers des modules du cœur listés un par un : dans les globs du socle, `promptforge/*.py` couvrirait aussi `promptforge/web/` (le `*` traverse les `/`).
- H5 `tests/conftest.py` et `tests/__init__.py` partagés (fixtures communes au cœur et au web).
- H6 La CI existante (`ci.yml` : lint + matrice 3.10–3.12) est gardée ; `controles.yml` s'y ajoute.
- H7 Numérotation reprise de l'historique : F-033, D-069, DEC-013.
