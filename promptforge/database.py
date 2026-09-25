"""
Gestion de la base de données SQLite pour PromptForge.
Stocke les projets et l'historique des prompts.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Project:
    id: int
    name: str
    config_path: str
    config_content: str
    created_at: str
    is_active: bool = False


@dataclass
class PromptHistory:
    id: int
    project_id: int
    raw_prompt: str
    formatted_prompt: str
    created_at: str
    file_path: str


class Database:
    def __init__(self, db_path: str = "promptforge.db"):
        self.db_path = Path(db_path)
        self.conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self):
        """Initialise la base de données et crée les tables si nécessaire."""
        # check_same_thread=False permet l'utilisation depuis plusieurs threads (Gradio)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                config_path TEXT NOT NULL,
                config_content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_active INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS prompt_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                raw_prompt TEXT NOT NULL,
                formatted_prompt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                file_path TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        self.conn.commit()

    def add_project(self, name: str, config_path: str, config_content: str) -> Project:
        """Ajoute un nouveau projet."""
        created_at = datetime.now().isoformat()

        cursor = self.conn.execute(
            """
            INSERT INTO projects (name, config_path, config_content, created_at, is_active)
            VALUES (?, ?, ?, ?, 0)
            """,
            (name, config_path, config_content, created_at),
        )
        self.conn.commit()

        return Project(
            id=cursor.lastrowid,
            name=name,
            config_path=config_path,
            config_content=config_content,
            created_at=created_at,
            is_active=False,
        )

    def update_project(self, name: str, config_content: str) -> bool:
        """Met à jour le contenu de configuration d'un projet."""
        cursor = self.conn.execute(
            "UPDATE projects SET config_content = ? WHERE name = ?", (config_content, name)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_project(self, name: str) -> Project | None:
        """Récupère un projet par son nom."""
        row = self.conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()

        if row:
            return Project(**dict(row))
        return None

    def get_active_project(self) -> Project | None:
        """Récupère le projet actuellement actif."""
        row = self.conn.execute("SELECT * FROM projects WHERE is_active = 1").fetchone()

        if row:
            return Project(**dict(row))
        return None

    def set_active_project(self, name: str) -> bool:
        """Définit un projet comme actif (désactive les autres)."""
        self.conn.execute("UPDATE projects SET is_active = 0")
        cursor = self.conn.execute("UPDATE projects SET is_active = 1 WHERE name = ?", (name,))
        self.conn.commit()
        return cursor.rowcount > 0

    def list_projects(self) -> list[Project]:
        """Liste tous les projets."""
        rows = self.conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return [Project(**dict(row)) for row in rows]

    def delete_project(self, name: str) -> bool:
        """Supprime un projet et son historique."""
        project = self.get_project(name)
        if not project:
            return False

        self.conn.execute("DELETE FROM prompt_history WHERE project_id = ?", (project.id,))
        self.conn.execute("DELETE FROM projects WHERE id = ?", (project.id,))
        self.conn.commit()
        return True

    def add_history(
        self, project_id: int, raw_prompt: str, formatted_prompt: str, file_path: str
    ) -> PromptHistory:
        """Ajoute une entrée dans l'historique."""
        created_at = datetime.now().isoformat()

        cursor = self.conn.execute(
            """
            INSERT INTO prompt_history (project_id, raw_prompt, formatted_prompt, created_at, file_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, raw_prompt, formatted_prompt, created_at, file_path),
        )
        self.conn.commit()

        return PromptHistory(
            id=cursor.lastrowid,
            project_id=project_id,
            raw_prompt=raw_prompt,
            formatted_prompt=formatted_prompt,
            created_at=created_at,
            file_path=file_path,
        )

    def get_history(self, project_name: str | None = None, limit: int = 20) -> list[PromptHistory]:
        """Récupère l'historique des prompts."""
        if project_name:
            project = self.get_project(project_name)
            if not project:
                return []
            rows = self.conn.execute(
                """
                SELECT * FROM prompt_history
                WHERE project_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (project.id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM prompt_history ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()

        return [PromptHistory(**dict(row)) for row in rows]

    def close(self):
        """Ferme la connexion à la base de données."""
        if self.conn:
            self.conn.close()
