"""SQLite database for Nibbl persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .models import (
    ConversationEntry,
    FamilyMember,
    Ingredient,
    MealHistoryEntry,
    MealPlanSession,
    MemberRole,
    Preference,
    Recipe,
    SessionState,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS family_members (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    imessage_id TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id TEXT NOT NULL REFERENCES family_members(id),
    category TEXT NOT NULL,
    detail TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    source TEXT DEFAULT 'conversation',
    extracted_from TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_preferences_member ON preferences(member_id);

CREATE TABLE IF NOT EXISTS meal_plan_sessions (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    triggered_by TEXT REFERENCES family_members(id),
    plan_start_date DATE,
    plan_end_date DATE,
    state_entered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recipes (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES meal_plan_sessions(id),
    planned_date DATE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    servings INTEGER DEFAULT 4,
    prep_time_minutes INTEGER,
    cook_time_minutes INTEGER,
    cuisine TEXT,
    tags TEXT,
    instructions TEXT,
    approved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_recipes_session ON recipes(session_id);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id TEXT NOT NULL REFERENCES recipes(id),
    name TEXT NOT NULL,
    quantity REAL,
    unit TEXT,
    category TEXT DEFAULT 'other',
    optional BOOLEAN DEFAULT FALSE,
    already_available BOOLEAN DEFAULT FALSE,
    picnic_product_id TEXT,
    picnic_product_name TEXT,
    picnic_added_to_cart BOOLEAN DEFAULT FALSE,
    search_status TEXT DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_ingredients_recipe ON recipe_ingredients(recipe_id);

CREATE TABLE IF NOT EXISTS conversation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES meal_plan_sessions(id),
    member_id TEXT REFERENCES family_members(id),
    direction TEXT NOT NULL,
    message_text TEXT NOT NULL,
    imessage_rowid INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_convlog_session ON conversation_log(session_id);

CREATE TABLE IF NOT EXISTS meal_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_name TEXT NOT NULL,
    cuisine TEXT,
    main_protein TEXT,
    tags TEXT,
    cooked_date DATE NOT NULL,
    rating REAL,
    session_id TEXT REFERENCES meal_plan_sessions(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    # --- Agent state (key-value) ---

    def get_state(self, key: str, default: str = "") -> str:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM agent_state WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default
        finally:
            conn.close()

    def set_state(self, key: str, value: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()

    # --- Family members ---

    def upsert_family_member(self, member: FamilyMember) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO family_members (id, name, imessage_id, role)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name,
                     imessage_id=excluded.imessage_id,
                     role=excluded.role""",
                (member.id, member.name, member.imessage_id, member.role),
            )
            conn.commit()
        finally:
            conn.close()

    def get_all_family_members(self) -> list[FamilyMember]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM family_members").fetchall()
            return [
                FamilyMember(
                    id=r["id"],
                    name=r["name"],
                    imessage_id=r["imessage_id"],
                    role=MemberRole(r["role"]),
                )
                for r in rows
            ]
        finally:
            conn.close()

    def get_member_by_imessage_id(self, imessage_id: str) -> FamilyMember | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM family_members WHERE imessage_id = ?", (imessage_id,)
            ).fetchone()
            if not row:
                return None
            return FamilyMember(
                id=row["id"],
                name=row["name"],
                imessage_id=row["imessage_id"],
                role=MemberRole(row["role"]),
            )
        finally:
            conn.close()

    def get_parents(self) -> list[FamilyMember]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM family_members WHERE role = 'parent'"
            ).fetchall()
            return [
                FamilyMember(
                    id=r["id"],
                    name=r["name"],
                    imessage_id=r["imessage_id"],
                    role=MemberRole.PARENT,
                )
                for r in rows
            ]
        finally:
            conn.close()

    # --- Preferences ---

    def add_preference(self, pref: Preference) -> int:
        conn = self._connect()
        try:
            cursor = conn.execute(
                """INSERT INTO preferences (member_id, category, detail, confidence, source, extracted_from)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    pref.member_id,
                    pref.category,
                    pref.detail,
                    pref.confidence,
                    pref.source,
                    pref.extracted_from,
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_preferences_for_member(self, member_id: str) -> list[Preference]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM preferences WHERE member_id = ? ORDER BY confidence DESC",
                (member_id,),
            ).fetchall()
            return [
                Preference(
                    id=r["id"],
                    member_id=r["member_id"],
                    category=r["category"],
                    detail=r["detail"],
                    confidence=r["confidence"],
                    source=r["source"],
                    extracted_from=r["extracted_from"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def get_all_preferences(self) -> list[Preference]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM preferences ORDER BY member_id, confidence DESC"
            ).fetchall()
            return [
                Preference(
                    id=r["id"],
                    member_id=r["member_id"],
                    category=r["category"],
                    detail=r["detail"],
                    confidence=r["confidence"],
                    source=r["source"],
                    extracted_from=r["extracted_from"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def update_preference_confidence(self, pref_id: int, confidence: float) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE preferences SET confidence = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (confidence, pref_id),
            )
            conn.commit()
        finally:
            conn.close()

    # --- Sessions ---

    def save_session(self, session: MealPlanSession) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO meal_plan_sessions
                   (id, state, triggered_by, plan_start_date, plan_end_date,
                    state_entered_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.id,
                    session.state.value,
                    session.triggered_by,
                    session.plan_start_date.isoformat() if session.plan_start_date else None,
                    session.plan_end_date.isoformat() if session.plan_end_date else None,
                    session.state_entered_at.isoformat(),
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_active_session(self) -> MealPlanSession | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT * FROM meal_plan_sessions
                   WHERE state NOT IN ('idle', 'completed')
                   ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
            if not row:
                return None
            return self._row_to_session(row)
        finally:
            conn.close()

    def get_session(self, session_id: str) -> MealPlanSession | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM meal_plan_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_session(row)
        finally:
            conn.close()

    def _row_to_session(self, row: sqlite3.Row) -> MealPlanSession:
        return MealPlanSession(
            id=row["id"],
            state=SessionState(row["state"]),
            triggered_by=row["triggered_by"],
            plan_start_date=(
                date.fromisoformat(row["plan_start_date"]) if row["plan_start_date"] else None
            ),
            plan_end_date=(
                date.fromisoformat(row["plan_end_date"]) if row["plan_end_date"] else None
            ),
            state_entered_at=datetime.fromisoformat(row["state_entered_at"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # --- Recipes ---

    def save_recipe(self, recipe: Recipe) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO recipes
                   (id, session_id, planned_date, name, description, servings,
                    prep_time_minutes, cook_time_minutes, cuisine, tags, instructions, approved)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    recipe.id,
                    recipe.session_id,
                    recipe.planned_date.isoformat(),
                    recipe.name,
                    recipe.description,
                    recipe.servings,
                    recipe.prep_time_minutes,
                    recipe.cook_time_minutes,
                    recipe.cuisine,
                    json.dumps(recipe.tags),
                    recipe.instructions,
                    recipe.approved,
                ),
            )
            # Save ingredients
            for ing in recipe.ingredients:
                conn.execute(
                    """INSERT INTO recipe_ingredients
                       (recipe_id, name, quantity, unit, category, optional,
                        already_available, picnic_product_id, picnic_product_name,
                        picnic_added_to_cart, search_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        recipe.id,
                        ing.name,
                        ing.quantity,
                        ing.unit,
                        ing.category,
                        ing.optional,
                        ing.already_available,
                        ing.picnic_product_id,
                        ing.picnic_product_name,
                        ing.picnic_added_to_cart,
                        ing.search_status,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def get_recipes_for_session(self, session_id: str) -> list[Recipe]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM recipes WHERE session_id = ? ORDER BY planned_date",
                (session_id,),
            ).fetchall()
            recipes = []
            for r in rows:
                ingredients = self._get_ingredients_for_recipe(conn, r["id"])
                recipes.append(
                    Recipe(
                        id=r["id"],
                        session_id=r["session_id"],
                        planned_date=date.fromisoformat(r["planned_date"]),
                        name=r["name"],
                        description=r["description"],
                        servings=r["servings"],
                        prep_time_minutes=r["prep_time_minutes"],
                        cook_time_minutes=r["cook_time_minutes"],
                        cuisine=r["cuisine"],
                        tags=json.loads(r["tags"]) if r["tags"] else [],
                        instructions=r["instructions"],
                        approved=bool(r["approved"]),
                        ingredients=ingredients,
                    )
                )
            return recipes
        finally:
            conn.close()

    def _get_ingredients_for_recipe(
        self, conn: sqlite3.Connection, recipe_id: str
    ) -> list[Ingredient]:
        rows = conn.execute(
            "SELECT * FROM recipe_ingredients WHERE recipe_id = ?", (recipe_id,)
        ).fetchall()
        return [
            Ingredient(
                id=r["id"],
                recipe_id=r["recipe_id"],
                name=r["name"],
                quantity=r["quantity"],
                unit=r["unit"],
                category=r["category"],
                optional=bool(r["optional"]),
                already_available=bool(r["already_available"]),
                picnic_product_id=r["picnic_product_id"],
                picnic_product_name=r["picnic_product_name"],
                picnic_added_to_cart=bool(r["picnic_added_to_cart"]),
                search_status=r["search_status"],
            )
            for r in rows
        ]

    def update_ingredient(self, ingredient: Ingredient) -> None:
        if ingredient.id is None:
            return
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE recipe_ingredients SET
                   already_available = ?, picnic_product_id = ?, picnic_product_name = ?,
                   picnic_added_to_cart = ?, search_status = ?
                   WHERE id = ?""",
                (
                    ingredient.already_available,
                    ingredient.picnic_product_id,
                    ingredient.picnic_product_name,
                    ingredient.picnic_added_to_cart,
                    ingredient.search_status,
                    ingredient.id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_recipes_approved(self, session_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE recipes SET approved = TRUE WHERE session_id = ?", (session_id,)
            )
            conn.commit()
        finally:
            conn.close()

    # --- Conversation log ---

    def log_conversation(self, entry: ConversationEntry) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO conversation_log
                   (session_id, member_id, direction, message_text, imessage_rowid)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    entry.session_id,
                    entry.member_id,
                    entry.direction,
                    entry.message_text,
                    entry.imessage_rowid,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_conversation_history(
        self, session_id: str, member_id: str | None = None, limit: int = 50
    ) -> list[ConversationEntry]:
        conn = self._connect()
        try:
            if member_id:
                rows = conn.execute(
                    """SELECT * FROM conversation_log
                       WHERE session_id = ? AND member_id = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (session_id, member_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM conversation_log
                       WHERE session_id = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (session_id, limit),
                ).fetchall()
            return [
                ConversationEntry(
                    id=r["id"],
                    session_id=r["session_id"],
                    member_id=r["member_id"],
                    direction=r["direction"],
                    message_text=r["message_text"],
                    imessage_rowid=r["imessage_rowid"],
                    created_at=r["created_at"],
                )
                for r in reversed(rows)  # chronological order
            ]
        finally:
            conn.close()

    # --- Meal history ---

    def add_meal_history(self, entry: MealHistoryEntry) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO meal_history
                   (recipe_name, cuisine, main_protein, tags, cooked_date, rating, session_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.recipe_name,
                    entry.cuisine,
                    entry.main_protein,
                    json.dumps(entry.tags),
                    entry.cooked_date.isoformat(),
                    entry.rating,
                    entry.session_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_meal_history(self, weeks: int = 3) -> list[MealHistoryEntry]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM meal_history
                   WHERE cooked_date >= date('now', ?)
                   ORDER BY cooked_date DESC""",
                (f"-{weeks * 7} days",),
            ).fetchall()
            return [
                MealHistoryEntry(
                    id=r["id"],
                    recipe_name=r["recipe_name"],
                    cuisine=r["cuisine"],
                    main_protein=r["main_protein"],
                    tags=json.loads(r["tags"]) if r["tags"] else [],
                    cooked_date=date.fromisoformat(r["cooked_date"]),
                    rating=r["rating"],
                    session_id=r["session_id"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def delete_recipes_for_session(self, session_id: str) -> None:
        """Delete all recipes and their ingredients for a session (used when regenerating)."""
        conn = self._connect()
        try:
            recipe_ids = conn.execute(
                "SELECT id FROM recipes WHERE session_id = ?", (session_id,)
            ).fetchall()
            for r in recipe_ids:
                conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (r["id"],))
            conn.execute("DELETE FROM recipes WHERE session_id = ?", (session_id,))
            conn.commit()
        finally:
            conn.close()
