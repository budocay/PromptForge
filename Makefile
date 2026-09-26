# PromptForge Makefile
# Usage: make <target>

.PHONY: help install install-dev test test-cov lint format clean docker-build docker-start docker-stop docker-status docker-logs docker-run docker-shell docker-clean docker-web build build-auto up down web

# Variables
# Surchargeable : make test PYTHON=.venv/bin/python
PYTHON ?= python3
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest
BLACK := $(PYTHON) -m black
RUFF := $(PYTHON) -m ruff
LINT_PATHS := promptforge/ tests/ scripts/ launcher.py start.py

# Fichier compose par defaut (DEC-010) : seule l'interface tourne en conteneur,
# Ollama reste natif sur l'hote. Il n'expose donc QU'UN service,
# `promptforge-web` : aucune cible ne doit nommer `ollama` ni `promptforge`
# sans passer un `-f` vers une variante qui les declare.
# Surchargeable : make docker-start COMPOSE_FILE=docker/compose/docker-compose.cpu.yml
COMPOSE_FILE ?= compose.yaml
COMPOSE := docker compose -f $(COMPOSE_FILE)

# Couleurs
BLUE := \033[34m
GREEN := \033[32m
YELLOW := \033[33m
NC := \033[0m

help: ## Afficher cette aide
	@echo "$(BLUE)PromptForge$(NC) - Reformateur intelligent de prompts"
	@echo ""
	@echo "$(GREEN)Targets disponibles:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'

# ============================================
# Installation
# ============================================

install: ## Installer le package
	$(PIP) install -e .

install-dev: ## Installer avec dépendances de développement
	$(PIP) install -e ".[dev]"

install-web: ## Installer avec interface web (Gradio)
	$(PIP) install -e ".[web]"

install-all: ## Installer toutes les dépendances
	$(PIP) install -e ".[all]"

# ============================================
# Tests
# ============================================

test: ## Lancer les tests
	$(PYTEST) tests/ -v

test-cov: ## Lancer les tests avec couverture
	$(PYTEST) tests/ -v --cov=promptforge --cov-report=html --cov-report=term-missing

test-fast: ## Lancer les tests sans les tests d'intégration
	$(PYTEST) tests/ -v -m "not integration"

# ============================================
# Qualité de code
# ============================================

lint: ## Vérifier le code avec ruff
	$(RUFF) check $(LINT_PATHS)

format: ## Formater le code avec black
	$(BLACK) $(LINT_PATHS)

format-check: ## Vérifier le formatage sans modifier
	$(BLACK) --check $(LINT_PATHS)

# ============================================
# Docker (cross-platform via Python)
# ============================================

docker-build: ## Construire l'image Docker
	$(COMPOSE) build

docker-start: ## Démarrer les services + vérifier le modèle Ollama
	$(PYTHON) scripts/docker_helper.py -f $(COMPOSE_FILE) start

docker-stop: ## Arrêter les services Docker
	$(PYTHON) scripts/docker_helper.py -f $(COMPOSE_FILE) stop

docker-status: ## Statut des services Docker
	$(PYTHON) scripts/build.py status

docker-logs: ## Logs de l'interface (usage: make docker-logs SERVICE=promptforge-web)
	$(PYTHON) scripts/docker_helper.py -f $(COMPOSE_FILE) logs $(SERVICE)

docker-run: ## Exécuter une commande (usage: make docker-run CMD="list")
	$(PYTHON) scripts/docker_helper.py -f $(COMPOSE_FILE) run $(CMD)

docker-shell: ## Shell interactif dans le conteneur
	$(PYTHON) scripts/docker_helper.py -f $(COMPOSE_FILE) shell

docker-clean: ## Supprimer conteneurs et volumes Docker
	$(PYTHON) scripts/build.py clean --force --images

# ============================================
# Build System (nouveau)
# ============================================

build: ## Construire les images Docker (compose.yaml, defaut DEC-010)
	$(PYTHON) scripts/build.py build

build-auto: ## Construire avec détection GPU (Ollama conteneurisé)
	$(PYTHON) scripts/build.py build -c auto

build-nvidia: ## Construire pour NVIDIA
	$(PYTHON) scripts/build.py build -c nvidia

build-amd: ## Construire pour AMD
	$(PYTHON) scripts/build.py build -c amd

build-cpu: ## Construire pour CPU
	$(PYTHON) scripts/build.py build -c cpu

rebuild: ## Reconstruire sans cache
	$(PYTHON) scripts/build.py build --no-cache

up: ## Démarrer les services (compose.yaml, defaut DEC-010)
	$(PYTHON) scripts/build.py up

down: ## Arrêter les services
	$(PYTHON) scripts/build.py down

launcher: ## Lancer le launcher GUI
	$(PYTHON) launcher.py

# ============================================
# Mise à jour Docker
# ============================================

update: ## Mettre à jour les images Docker (pull + rebuild + restart)
	@echo "$(BLUE)🔄 Mise à jour PromptForge...$(NC)"
	$(COMPOSE) pull
	$(COMPOSE) build
	$(COMPOSE) up -d
	@echo "$(GREEN)✅ Mise à jour terminée!$(NC)"
	$(COMPOSE) ps

update-force: ## Forcer reconstruction complète (sans cache)
	@echo "$(YELLOW)🔄 Reconstruction forcée (sans cache)...$(NC)"
	$(COMPOSE) down
	$(COMPOSE) build --no-cache --pull
	$(COMPOSE) up -d
	@echo "$(GREEN)✅ Reconstruction terminée!$(NC)"
	$(COMPOSE) ps

update-all: ## Mettre à jour + nettoyer les anciennes images
	@echo "$(BLUE)🔄 Mise à jour complète...$(NC)"
	$(COMPOSE) down
	$(COMPOSE) pull
	$(COMPOSE) build --no-cache
	docker image prune -f
	$(COMPOSE) up -d
	@echo "$(GREEN)✅ Mise à jour complète terminée!$(NC)"
	$(COMPOSE) ps

# ============================================
# Docker AMD GPU (ROCm)
# ============================================

docker-amd: ## Démarrer avec GPU AMD (ROCm) - modèle 14B
	@echo "$(BLUE)🎮 Démarrage avec GPU AMD (qwen2.5:14b)...$(NC)"
	docker compose -f docker/compose/docker-compose.amd.yml up -d
	@echo "$(GREEN)✅ Interface: http://localhost:7860$(NC)"

docker-amd-max: ## Démarrer avec GPU AMD - modèle 32B (max qualité)
	@echo "$(BLUE)🎮 Démarrage avec GPU AMD MAX (qwen2.5:32b)...$(NC)"
	@echo "$(YELLOW)⚠️  Premier lancement: téléchargement ~18GB$(NC)"
	docker compose -f docker/compose/docker-compose.amd-max.yml up -d
	@echo "$(GREEN)✅ Interface: http://localhost:7860$(NC)"

docker-amd-stop: ## Arrêter les services AMD
	docker compose -f docker/compose/docker-compose.amd.yml down 2>/dev/null || true
	docker compose -f docker/compose/docker-compose.amd-max.yml down 2>/dev/null || true

docker-amd-logs: ## Logs AMD (vérifier détection GPU)
	docker compose -f docker/compose/docker-compose.amd.yml logs ollama 2>/dev/null || \
	docker compose -f docker/compose/docker-compose.amd-max.yml logs ollama

# ============================================
# Interface Web
# ============================================

web: ## Lancer l'interface web Gradio
	promptforge web

web-public: ## Lancer l'interface web avec lien public
	promptforge web --host 0.0.0.0 --share

docker-web: ## Lancer l'interface web via Docker
	$(PYTHON) scripts/docker_helper.py -f $(COMPOSE_FILE) web

# ============================================
# Développement
# ============================================

dev-setup: install-dev ## Setup complet pour développement
	@echo "$(GREEN)✓ Environnement de développement prêt$(NC)"

check: lint format-check test ## Vérifications complètes (lint + format + tests)
	@echo "$(GREEN)✓ Toutes les vérifications passées$(NC)"

# ============================================
# Nettoyage
# ============================================

clean: ## Nettoyer les fichiers générés
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

clean-data: ## Nettoyer les données (DB + historique)
	rm -f promptforge.db
	rm -rf history/*
	@echo "$(YELLOW)⚠ Données supprimées$(NC)"

# ============================================
# Release
# ============================================

build-dist: clean ## Construire le package pour distribution
	$(PYTHON) -m build

publish-test: build-dist ## Publier sur TestPyPI
	$(PYTHON) -m twine upload --repository testpypi dist/*

publish: build-dist ## Publier sur PyPI
	$(PYTHON) -m twine upload dist/*
