"""Data models for FoodAgend."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class MemberRole(str, Enum):
    PARENT = "parent"
    CHILD = "child"


class SessionState(str, Enum):
    IDLE = "idle"
    COLLECTING_PREFERENCES = "collecting_preferences"
    GENERATING_PLAN = "generating_plan"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPILING_INGREDIENTS = "compiling_ingredients"
    CHECKING_PANTRY = "checking_pantry"
    FILLING_CART = "filling_cart"
    CART_REVIEW = "cart_review"
    COMPLETED = "completed"


class PreferenceCategory(str, Enum):
    LIKES = "likes"
    DISLIKES = "dislikes"
    ALLERGY = "allergy"
    DIETARY = "dietary"
    CUISINE_PREFERENCE = "cuisine_preference"
    SPECIFIC_WISH = "specific_wish"
    GENERAL = "general"


class IngredientCategory(str, Enum):
    PRODUCE = "produce"
    DAIRY = "dairy"
    MEAT = "meat"
    FISH = "fish"
    PANTRY = "pantry"
    SPICE = "spice"
    BAKERY = "bakery"
    FROZEN = "frozen"
    OTHER = "other"


class SearchStatus(str, Enum):
    PENDING = "pending"
    FOUND = "found"
    NOT_FOUND = "not_found"
    SKIPPED = "skipped"


@dataclass
class FamilyMember:
    id: str
    name: str
    imessage_id: str  # phone number like "+31612345678" or email
    role: MemberRole

    @classmethod
    def create(cls, name: str, imessage_id: str, role: MemberRole) -> FamilyMember:
        return cls(id=str(uuid.uuid4()), name=name, imessage_id=imessage_id, role=role)


@dataclass
class Preference:
    member_id: str
    category: str
    detail: str
    confidence: float = 0.5
    source: str = "conversation"
    extracted_from: str | None = None
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Ingredient:
    name: str
    quantity: float
    unit: str
    category: str = "other"
    optional: bool = False
    already_available: bool = False
    picnic_product_id: str | None = None
    picnic_product_name: str | None = None
    picnic_added_to_cart: bool = False
    search_status: str = "pending"
    id: int | None = None
    recipe_id: str | None = None


@dataclass
class Recipe:
    id: str
    name: str
    description: str
    planned_date: date
    servings: int
    prep_time_minutes: int
    cook_time_minutes: int
    cuisine: str
    tags: list[str]
    ingredients: list[Ingredient]
    instructions: str
    session_id: str | None = None
    approved: bool = False

    @classmethod
    def create(cls, **kwargs) -> Recipe:
        kwargs.setdefault("id", str(uuid.uuid4()))
        return cls(**kwargs)


@dataclass
class MealPlan:
    recipes: list[Recipe]
    reasoning: str


@dataclass
class MealPlanSession:
    id: str
    state: SessionState
    triggered_by: str | None = None  # member_id
    plan_start_date: date | None = None
    plan_end_date: date | None = None
    state_entered_at: datetime = field(default_factory=datetime.now)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Transient state (not persisted to DB, rebuilt at runtime)
    meal_plan: MealPlan | None = field(default=None, repr=False)
    collected_wishes: dict[str, list[str]] = field(default_factory=dict)
    members_responded: set[str] = field(default_factory=set)
    approval_feedback: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, triggered_by: str | None = None) -> MealPlanSession:
        return cls(
            id=str(uuid.uuid4()),
            state=SessionState.IDLE,
            triggered_by=triggered_by,
        )

    def transition_to(self, new_state: SessionState) -> None:
        self.state = new_state
        self.state_entered_at = datetime.now()
        self.updated_at = datetime.now()


@dataclass
class IncomingMessage:
    rowid: int
    text: str
    sender_id: str  # phone number or email from handle table
    is_from_me: bool = False
    chat_identifier: str | None = None
    group_name: str | None = None
    timestamp: datetime | None = None


@dataclass
class ConversationEntry:
    session_id: str | None
    member_id: str | None
    direction: str  # "incoming" or "outgoing"
    message_text: str
    imessage_rowid: int | None = None
    id: int | None = None
    created_at: datetime | None = None


@dataclass
class MealHistoryEntry:
    recipe_name: str
    cuisine: str | None
    main_protein: str | None
    tags: list[str]
    cooked_date: date
    rating: float | None = None
    session_id: str | None = None
    id: int | None = None


@dataclass
class CartReport:
    added: list[tuple[Ingredient, dict]] = field(default_factory=list)
    not_found: list[tuple[Ingredient, str]] = field(default_factory=list)
    skipped: list[Ingredient] = field(default_factory=list)
    errors: list[tuple[Ingredient, str]] = field(default_factory=list)
