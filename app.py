
import base64
import io
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import imagehash
import pandas as pd
import streamlit as st
from PIL import Image, ImageOps
from supabase import Client, create_client

# ------------------------------------------------------------
# Page configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="IBS Marketplace",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------
# Styling
# ------------------------------------------------------------
st.markdown(
    """
    <style>
    .main { background: #f7f8fb; }
    .block-container { padding-top: 1.2rem; }
    .market-title { font-size: 2.2rem; font-weight: 800; letter-spacing: -0.5px; }
    .muted { color: #6b7280; }
    .pill {
        display:inline-block; padding:0.25rem 0.55rem; margin:0.12rem;
        border-radius:999px; background:#eef2ff; font-size:0.78rem;
    }
    .card {
        padding: 1rem; border-radius: 16px; background: white;
        border: 1px solid #e5e7eb; margin-bottom: 0.7rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.03);
    }
    .price { font-size: 1.45rem; font-weight: 800; }
    .small { font-size: 0.82rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------
DOMAIN = "ibsindia.org"

CATEGORIES = [
    "Books",
    "Stationery",
    "Electronics",
    "Appliances",
    "Hostel Essentials",
    "Other",
]

CONDITIONS = ["New", "Like New", "Good", "Fair", "Well Used"]

LISTING_TYPES = ["Sell", "Rent", "Trade"]

BLOCKS = list("ABCDEFGH") + ["T"]
MEETUP_ZONES = [
    "A Block", "B Block", "C Block", "D Block", "E Block",
    "F Block", "G Block", "H Block", "T Block",
    "Library Reading Room",
    "Other Safe Campus Zone",
]


# ------------------------------------------------------------
# Secrets / configuration
# ------------------------------------------------------------
def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        value = st.secrets.get(name, None)
        if value is not None:
            return str(value)
    except Exception:
        pass
    return os.getenv(name, default)


# ------------------------------------------------------------
# Secrets / configuration
# ------------------------------------------------------------

def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        if name in st.secrets:
            value = st.secrets[name]

            if value is not None and str(value).strip():
                return str(value).strip()

    except Exception as exc:
        st.error(f"Could not read Streamlit secret '{name}': {exc}")

    value = os.getenv(name, default)

    if value is not None and str(value).strip():
        return str(value).strip()

    return default


SUPABASE_URL = get_secret("SUPABASE_URL")

SUPABASE_KEY = (
    get_secret("SUPABASE_SECRET_KEY")
    or get_secret("SUPABASE_SERVICE_ROLE_KEY")
    or get_secret("SUPABASE_KEY")
)

OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
OPENAI_MODEL = get_secret("OPENAI_MODEL", "gpt-4.1-mini")


@st.cache_resource
def get_supabase() -> Optional[Client]:
    if not SUPABASE_URL:
        st.error(
            "❌ SUPABASE_URL is missing. "
            "Add SUPABASE_URL in Streamlit Cloud → Settings → Secrets."
        )
        return None

    if not SUPABASE_KEY:
        st.error(
            "❌ SUPABASE_SECRET_KEY is missing. "
            "Add SUPABASE_SECRET_KEY in Streamlit Cloud → Settings → Secrets."
        )
        return None

    if not SUPABASE_URL.startswith("https://"):
        st.error(
            "❌ SUPABASE_URL does not look valid. "
            "It should start with https://"
        )
        return None

    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return client

    except Exception as exc:
        st.error(f"❌ Could not connect to Supabase: {exc}")
        return None


db = get_supabase()




# ------------------------------------------------------------
# Authentication
# ------------------------------------------------------------
def require_ibs_login() -> bool:
    try:
        logged_in = bool(st.user.is_logged_in)
    except Exception:
        st.error(
            "Google OIDC is not configured yet. Add the [auth] and [auth.google] "
            "settings from the included secrets template to Streamlit Cloud."
        )
        st.stop()

    if not logged_in:
        st.markdown("<div class='market-title'>🛍️ IBS Marketplace</div>", unsafe_allow_html=True)
        st.write(
            "A campus-only peer-to-peer marketplace for IBS students."
        )
        st.info("Access is restricted to verified @ibsindia.org Google accounts.")
        if st.button("Continue with Google", type="primary", use_container_width=False):
            st.login("google")
        st.stop()

    user = st.user
    email = str(getattr(user, "email", "")).lower().strip()
    hosted_domain = str(getattr(user, "hd", "")).lower().strip()

    # Do NOT rely on the Google account-picker hint alone.
    # Verify the returned identity claims inside the app.
    if not email.endswith(f"@{DOMAIN}") or hosted_domain != DOMAIN:
        st.error("This marketplace is restricted to authenticated @ibsindia.org accounts.")
        st.caption(f"Signed-in account: {email or 'unknown'}")
        if st.button("Sign out"):
            st.logout()
        st.stop()

    return True


require_ibs_login()


# ------------------------------------------------------------
# User identity
# ------------------------------------------------------------
def current_user() -> Dict[str, str]:
    user = st.user
    return {
        "google_sub": str(getattr(user, "sub", "")),
        "email": str(getattr(user, "email", "")).lower().strip(),
        "name": str(getattr(user, "name", "") or getattr(user, "email", "")),
        "avatar_url": str(getattr(user, "picture", "") or ""),
    }


ME = current_user()


# ------------------------------------------------------------
# Database helpers
# ------------------------------------------------------------
def db_required() -> Client:
    if db is None:
        st.error(
            "Supabase is not configured. Add SUPABASE_URL and SUPABASE_SECRET_KEY "
            "in Streamlit Cloud → Settings → Secrets."
        )
        st.stop()
    return db


def safe_execute(fn, fallback=None):
    try:
        result = fn()
        return result.data if hasattr(result, "data") else result
    except Exception as exc:
        st.error(f"Database operation failed: {exc}")
        return fallback


def ensure_profile() -> Optional[Dict[str, Any]]:
    client = db_required()
    payload = {
        "google_sub": ME["google_sub"],
        "email": ME["email"],
        "display_name": ME["name"][:120],
        "avatar_url": ME["avatar_url"][:500],
    }
    rows = safe_execute(
        lambda: client.table("profiles")
        .upsert(payload, on_conflict="google_sub")
        .execute(),
        [],
    )
    return rows[0] if rows else None


PROFILE = ensure_profile()
USER_ID = PROFILE["id"] if PROFILE else None


def query_listings(include_demo=False) -> List[Dict[str, Any]]:
    client = db_required()
    rows = safe_execute(
        lambda: client.table("listings")
        .select("*")
        .order("created_at", desc=True)
        .execute(),
        [],
    )
    if include_demo or rows:
        return rows
    return []


@st.cache_data(ttl=10)
def cached_transactions(category: Optional[str] = None) -> pd.DataFrame:
    client = db_required()
    query = client.table("transactions").select(
        "sale_price, category, item_condition, original_price, completed_at"
    )
    if category:
        query = query.eq("category", category)
    rows = safe_execute(lambda: query.execute(), [])
    return pd.DataFrame(rows)


# ------------------------------------------------------------
# Image helpers
# ------------------------------------------------------------
def image_to_storage(uploaded_file) -> Optional[Dict[str, str]]:
    if uploaded_file is None:
        return None
    try:
        image = Image.open(uploaded_file).convert("RGB")
        image.thumbnail((900, 900))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=78, optimize=True)
        raw = buffer.getvalue()
        encoded = base64.b64encode(raw).decode("utf-8")
        phash = str(imagehash.phash(image))
        return {"image_data": encoded, "image_hash": phash}
    except Exception as exc:
        st.error(f"Could not process the image: {exc}")
        return None


def show_listing_image(encoded: Optional[str], width: int = 360):
    if not encoded:
        st.markdown("📦", unsafe_allow_html=True)
        return
    try:
        image = Image.open(io.BytesIO(base64.b64decode(encoded)))
        st.image(image, width=width)
    except Exception:
        st.caption("Image unavailable")


def visual_distance(query_image: Image.Image, stored_hash: Optional[str]) -> Optional[int]:
    if not stored_hash:
        return None
    try:
        qh = imagehash.phash(query_image.convert("RGB"))
        sh = imagehash.hex_to_hash(stored_hash)
        return qh - sh
    except Exception:
        return None


# ------------------------------------------------------------
# AI helpers
# ------------------------------------------------------------
def call_ai(instruction: str) -> Optional[str]:
    if not OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=instruction,
        )
        return response.output_text.strip()
    except Exception:
        return None


def estimate_fair_price(
    title: str,
    category: str,
    condition: str,
    age_months: int,
    original_price: float,
    historical_df: pd.DataFrame,
) -> Dict[str, Any]:
    # Campus transaction benchmark
    if not historical_df.empty:
        hist = pd.to_numeric(historical_df["sale_price"], errors="coerce").dropna()
    else:
        hist = pd.Series(dtype=float)

    median_price = float(hist.median()) if not hist.empty else 0.0

    condition_factor = {
        "New": 0.90,
        "Like New": 0.78,
        "Good": 0.65,
        "Fair": 0.50,
        "Well Used": 0.35,
    }[condition]

    age_factor = max(0.35, 1 - min(age_months, 60) * 0.01)
    baseline = original_price * condition_factor * age_factor

    if median_price > 0:
        baseline = (baseline * 0.60) + (median_price * 0.40)

    baseline = max(50.0, round(baseline / 50) * 50)

    prompt = f"""
You are the fair-price assistant for IBS Marketplace, a private campus marketplace.
Recommend a reasonable listing price in Indian rupees.

Item title: {title}
Category: {category}
Condition: {condition}
Approximate age: {age_months} months
Original/new price: ₹{original_price:,.0f}
Campus historical median transaction price, when available: ₹{median_price:,.0f}

Calculated benchmark: ₹{baseline:,.0f}

Give:
1) recommended listing price,
2) reasonable negotiation range,
3) 2-3 short reasons.
Do not invent exact transaction records.
"""
    ai_text = call_ai(prompt)

    return {
        "benchmark": baseline,
        "historical_median": median_price,
        "ai_text": ai_text,
    }


def negotiation_suggestion(
    role: str,
    title: str,
    listing_price: float,
    offer: float,
    price_floor: Optional[float],
    condition: str,
) -> str:
    floor_text = (
        f"Seller private floor: ₹{price_floor:,.0f}"
        if price_floor is not None
        else "Seller private floor: not available"
    )
    prompt = f"""
You are the negotiation assistant for a campus marketplace.

Role: {role}
Item: {title}
Condition: {condition}
Listing price: ₹{listing_price:,.0f}
Incoming/current offer: ₹{offer:,.0f}
{floor_text}

Rules:
- Never reveal the seller's private floor to the buyer.
- Never fabricate market facts.
- Recommend a practical counter-offer or opening offer.
- Keep the response under 80 words.
- Include a ready-to-send message.
"""
    ai_text = call_ai(prompt)
    if ai_text:
        return ai_text

    if role == "seller":
        floor = price_floor if price_floor is not None else listing_price * 0.80
        if offer >= floor:
            counter = max(offer, round(listing_price * 0.95 / 50) * 50)
            return (
                f"Suggested counter: ₹{counter:,.0f}. "
                "Ready reply: “I can come down a little. Would ₹"
                f"{counter:,.0f} work for you?”"
            )
        counter = max(floor, round(((offer + listing_price) / 2) / 50) * 50)
        return (
            f"Suggested counter: ₹{counter:,.0f}. "
            "Ready reply: “Thanks for the offer. I can do ₹"
            f"{counter:,.0f} as my best campus price.”"
        )

    opening = min(listing_price, round(offer / 50) * 50)
    return (
        f"Suggested offer: ₹{opening:,.0f}. "
        "Ready reply: “Hi! I’m interested. Would you consider ₹"
        f"{opening:,.0f} for this item?”"
    )


# ------------------------------------------------------------
# Watchlist
# ------------------------------------------------------------
def is_watched(listing_id: str) -> bool:
    client = db_required()
    rows = safe_execute(
        lambda: client.table("watchlists")
        .select("id")
        .eq("user_id", USER_ID)
        .eq("listing_id", listing_id)
        .limit(1)
        .execute(),
        [],
    )
    return bool(rows)


def toggle_watchlist(listing_id: str):
    client = db_required()
    if is_watched(listing_id):
        safe_execute(
            lambda: client.table("watchlists")
            .delete()
            .eq("user_id", USER_ID)
            .eq("listing_id", listing_id)
            .execute(),
            [],
        )
    else:
        safe_execute(
            lambda: client.table("watchlists")
            .insert({"user_id": USER_ID, "listing_id": listing_id})
            .execute(),
            [],
        )
    st.rerun()


# ------------------------------------------------------------
# Conversations / messages
# ------------------------------------------------------------
def get_or_create_conversation(listing_id: str, seller_id: str) -> Optional[str]:
    client = db_required()

    existing = safe_execute(
        lambda: client.table("conversations")
        .select("id")
        .eq("listing_id", listing_id)
        .eq("buyer_id", USER_ID)
        .eq("seller_id", seller_id)
        .limit(1)
        .execute(),
        [],
    )
    if existing:
        return existing[0]["id"]

    created = safe_execute(
        lambda: client.table("conversations")
        .insert({
            "listing_id": listing_id,
            "buyer_id": USER_ID,
            "seller_id": seller_id,
        })
        .execute(),
        [],
    )
    return created[0]["id"] if created else None


def get_conversations() -> List[Dict[str, Any]]:
    client = db_required()
    rows = safe_execute(
        lambda: client.table("conversations")
        .select("*")
        .or_(f"buyer_id.eq.{USER_ID},seller_id.eq.{USER_ID}")
        .order("updated_at", desc=True)
        .execute(),
        [],
    )
    return rows


def get_messages(conversation_id: str) -> List[Dict[str, Any]]:
    client = db_required()
    return safe_execute(
        lambda: client.table("messages")
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        .execute(),
        [],
    )


def send_message(conversation_id: str, text: str):
    client = db_required()
    text = text.strip()
    if not text:
        return
    safe_execute(
        lambda: client.table("messages")
        .insert({
            "conversation_id": conversation_id,
            "sender_id": USER_ID,
            "body": text[:2000],
        })
        .execute(),
        [],
    )
    safe_execute(
        lambda: client.table("conversations")
        .update({"updated_at": datetime.utcnow().isoformat()})
        .eq("id", conversation_id)
        .execute(),
        [],
    )


# ------------------------------------------------------------
# UI: sidebar
# ------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🛍️ IBS Marketplace")
    st.caption(ME["email"])

    nav = st.radio(
        "Navigate",
        ["Browse", "Visual Search", "Sell an Item", "Chats", "My Listings", "Watchlist", "Profile"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.caption("Campus-only • @ibsindia.org")
    if st.button("Sign out", use_container_width=True):
        st.logout()


# ------------------------------------------------------------
# Listing card
# ------------------------------------------------------------
def listing_card(item: Dict[str, Any]):
    seller_name = item.get("seller_name", "IBS Student")
    price = item.get("price", 0) or 0
    with st.container(border=True):
        cols = st.columns([1, 2.2, 1])
        with cols[0]:
            show_listing_image(item.get("image_data"), width=180)

        with cols[1]:
            st.markdown(f"### {item.get('title', 'Untitled item')}")
            badges = [
                item.get("category", "Other"),
                item.get("condition", "Good"),
                item.get("listing_type", "Sell"),
            ]
            st.markdown(
                " ".join([f"<span class='pill'>{b}</span>" for b in badges]),
                unsafe_allow_html=True,
            )
            st.write(item.get("description", "No description."))
            st.caption(
                f"📍 {item.get('meetup_zone', 'Campus')}  •  👤 {seller_name}"
            )

        with cols[2]:
            st.markdown(f"<div class='price'>₹{price:,.0f}</div>", unsafe_allow_html=True)
            st.caption("Trade/rent terms may vary.")
            watched = is_watched(item["id"])
            if st.button(
                "★ Watching" if watched else "☆ Watch",
                key=f"watch_{item['id']}",
                use_container_width=True,
            ):
                toggle_watchlist(item["id"])

            if item.get("seller_id") != USER_ID:
                if st.button(
                    "Contact seller",
                    key=f"contact_{item['id']}",
                    use_container_width=True,
                ):
                    conv_id = get_or_create_conversation(item["id"], item["seller_id"])
                    if conv_id:
                        st.session_state["active_conversation_id"] = conv_id
                        st.session_state["nav_to_chats"] = True
                        st.rerun()
            else:
                st.caption("Your listing")


# ------------------------------------------------------------
# Browse
# ------------------------------------------------------------
def browse_page():
    st.markdown("<div class='market-title'>🛍️ Browse IBS Marketplace</div>", unsafe_allow_html=True)
    st.caption("Buy, sell, rent and trade items within the IBS student community.")

    listings = query_listings()
    if not listings:
        st.info(
            "No listings yet. Be the first to list a textbook, appliance, electronic, "
            "stationery item or hostel essential."
        )
        return

    # Add seller names
    seller_ids = sorted({x["seller_id"] for x in listings if x.get("seller_id")})
    seller_map = {}
    client = db_required()
    if seller_ids:
        profiles = safe_execute(
            lambda: client.table("profiles")
            .select("id,display_name")
            .in_("id", seller_ids)
            .execute(),
            [],
        )
        seller_map = {p["id"]: p["display_name"] for p in profiles}
    for item in listings:
        item["seller_name"] = seller_map.get(item.get("seller_id"), "IBS Student")

    with st.expander("🔎 Multi-parameter filters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            search = st.text_input("Search", placeholder="e.g., calculator, finance book")
            category = st.multiselect("Category", CATEGORIES)
        with c2:
            listing_type = st.multiselect("Type", LISTING_TYPES)
            condition = st.multiselect("Condition", CONDITIONS)
        with c3:
            meetup = st.multiselect("Pickup / meetup zone", MEETUP_ZONES)
            min_price = st.number_input("Min ₹", min_value=0, value=0, step=100)
        with c4:
            max_price = st.number_input("Max ₹", min_value=0, value=100000, step=500)
            sort_by = st.selectbox("Sort by", ["Newest", "Price: Low to High", "Price: High to Low"])

    filtered = []
    for item in listings:
        haystack = " ".join([
            str(item.get("title", "")),
            str(item.get("description", "")),
            str(item.get("tags", "")),
        ]).lower()

        if search and search.lower() not in haystack:
            continue
        if category and item.get("category") not in category:
            continue
        if listing_type and item.get("listing_type") not in listing_type:
            continue
        if condition and item.get("condition") not in condition:
            continue
        if meetup and item.get("meetup_zone") not in meetup:
            continue

        price = float(item.get("price") or 0)
        if price < min_price or price > max_price:
            continue

        if item.get("status", "active") == "active":
            filtered.append(item)

    if sort_by == "Price: Low to High":
        filtered.sort(key=lambda x: float(x.get("price") or 0))
    elif sort_by == "Price: High to Low":
        filtered.sort(key=lambda x: float(x.get("price") or 0))

    st.write(f"**{len(filtered)} active listing(s)**")

    for item in filtered:
        listing_card(item)


# ------------------------------------------------------------
# Visual search
# ------------------------------------------------------------
def visual_search_page():
    st.markdown("<div class='market-title'>🖼️ Visual Search</div>", unsafe_allow_html=True)
    st.caption(
        "Upload a photo of a textbook, device or hostel item. IBS Marketplace compares "
        "the image against listing image fingerprints stored in the marketplace."
    )

    uploaded = st.file_uploader(
        "Upload a reference image",
        type=["jpg", "jpeg", "png", "webp"],
        key="visual_query",
    )
    threshold = st.slider("Visual similarity threshold (lower = stricter)", 0, 20, 12)

    if uploaded is None:
        st.info("Upload an image to start a visual search.")
        return

    query_image = Image.open(uploaded).convert("RGB")
    st.image(query_image, caption="Your reference image", width=260)

    listings = [
        x for x in query_listings()
        if x.get("status", "active") == "active" and x.get("image_hash")
    ]

    ranked = []
    for item in listings:
        distance = visual_distance(query_image, item.get("image_hash"))
        if distance is not None and distance <= threshold:
            ranked.append((distance, item))

    ranked.sort(key=lambda x: x[0])

    if not ranked:
        st.warning(
            "No close visual matches were found. Try a larger threshold or use text filters "
            "on the Browse page."
        )
        return

    st.write(f"**{len(ranked)} possible match(es)**")
    for distance, item in ranked[:20]:
        st.caption(f"Visual distance: {distance}")
        listing_card(item)


# ------------------------------------------------------------
# Sell
# ------------------------------------------------------------
def sell_page():
    st.markdown("<div class='market-title'>➕ List an item</div>", unsafe_allow_html=True)
    st.caption("Keep the listing transparent: show the condition, price logic and safe meetup zone.")

    with st.form("sell_form"):
        title = st.text_input("Item title *", placeholder="e.g., Financial Management textbook")
        category = st.selectbox("Category", CATEGORIES)
        listing_type = st.selectbox("Trade type", LISTING_TYPES)
        condition = st.selectbox("Condition", CONDITIONS)
        age_months = st.number_input("Approx. age (months)", min_value=0, max_value=240, value=12, step=1)
        original_price = st.number_input("Original/new price ₹", min_value=0, value=1000, step=50)
        price = st.number_input("Your listing price ₹", min_value=0, value=700, step=50)
        price_floor = st.number_input(
            "Private minimum acceptable price ₹",
            min_value=0,
            value=500,
            step=50,
            help="Visible only to the seller and used by the negotiation assistant.",
        )
        meetup_zone = st.selectbox("Preferred pickup / meetup", MEETUP_ZONES)
        tags = st.text_input("Search tags", placeholder="semester, calculator, hostel, finance")
        description = st.text_area("Description *", placeholder="Mention defects, accessories, edition, warranty, etc.")
        image_file = st.file_uploader(
            "Item image",
            type=["jpg", "jpeg", "png", "webp"],
        )

        submitted = st.form_submit_button("Create listing", type="primary")

    if st.button("🤖 Estimate a fair market price"):
        hist = cached_transactions(category)
        result = estimate_fair_price(
            title or "Campus item",
            category,
            condition,
            int(age_months),
            float(original_price),
            hist,
        )
        st.session_state["estimated_price"] = result["benchmark"]
        st.session_state["estimate_text"] = result["ai_text"]
        st.session_state["estimate_median"] = result["historical_median"]

    if "estimated_price" in st.session_state:
        st.success(
            f"Benchmark listing price: ₹{st.session_state['estimated_price']:,.0f}"
        )
        median = st.session_state.get("estimate_median", 0)
        if median:
            st.caption(f"Campus historical median used: ₹{median:,.0f}")
        if st.session_state.get("estimate_text"):
            st.write(st.session_state["estimate_text"])
        else:
            st.caption("AI key not configured; the benchmark uses condition, age and campus transaction history.")

    if submitted:
        if not title.strip() or not description.strip():
            st.error("Item title and description are required.")
            return
        if price_floor > price:
            st.error("Private minimum price cannot be above the listing price.")
            return

        image_payload = image_to_storage(image_file)
        row = {
            "seller_id": USER_ID,
            "title": title.strip()[:150],
            "category": category,
            "listing_type": listing_type,
            "condition": condition,
            "age_months": int(age_months),
            "original_price": float(original_price),
            "price": float(price),
            "price_floor": float(price_floor),
            "meetup_zone": meetup_zone,
            "tags": tags[:300],
            "description": description.strip()[:2500],
            "image_data": image_payload["image_data"] if image_payload else None,
            "image_hash": image_payload["image_hash"] if image_payload else None,
            "status": "active",
        }

        client = db_required()
        created = safe_execute(lambda: client.table("listings").insert(row).execute(), [])
        if created:
            st.success("Listing created successfully.")
            st.session_state.pop("estimated_price", None)
            cached_transactions.clear()
        else:
            st.error("The listing could not be created.")


# ------------------------------------------------------------
# Chats
# ------------------------------------------------------------
def chats_page():
    st.markdown("<div class='market-title'>💬 Campus Chat</div>", unsafe_allow_html=True)
    st.caption(
        "Private conversations are limited to authenticated campus participants in the transaction."
    )

    conversations = get_conversations()

    if not conversations:
        st.info("No conversations yet. Open a listing and select “Contact seller”.")
        return

    # Resolve listing information
    listing_ids = list({c["listing_id"] for c in conversations})
    client = db_required()
    listings = safe_execute(
        lambda: client.table("listings")
        .select("id,title,price,condition,seller_id,price_floor")
        .in_("id", listing_ids)
        .execute(),
        [],
    )
    listing_map = {x["id"]: x for x in listings}

    labels = []
    for c in conversations:
        listing = listing_map.get(c["listing_id"], {})
        role = "Seller" if c["seller_id"] == USER_ID else "Buyer"
        labels.append(f"{listing.get('title', 'Item')} • {role}")

    default_index = 0
    active_id = st.session_state.get("active_conversation_id")
    if active_id:
        for i, c in enumerate(conversations):
            if c["id"] == active_id:
                default_index = i
                break

    selected_label = st.selectbox("Conversation", labels, index=default_index)
    selected = conversations[labels.index(selected_label)]
    st.session_state["active_conversation_id"] = selected["id"]

    listing = listing_map.get(selected["listing_id"], {})
    role = "seller" if selected["seller_id"] == USER_ID else "buyer"

    st.markdown(
        f"**{listing.get('title', 'Item')}** · ₹{float(listing.get('price', 0)):,.0f} · "
        f"{listing.get('condition', 'Good')}"
    )

    @st.fragment(run_every="3s")
    def live_chat():
        messages = get_messages(selected["id"])
        for msg in messages:
            author = "You" if msg["sender_id"] == USER_ID else "Campus peer"
            with st.chat_message("user" if msg["sender_id"] == USER_ID else "assistant"):
                st.caption(author)
                st.write(msg["body"])

        c1, c2 = st.columns([5, 1])
        with c1:
            text = st.text_input(
                "Message",
                key=f"message_box_{selected['id']}",
                placeholder="Type a message...",
                label_visibility="collapsed",
            )
        with c2:
            send = st.button("Send", key=f"send_{selected['id']}", use_container_width=True)

        if send and text.strip():
            send_message(selected["id"], text)
            st.rerun()

    live_chat()

    st.markdown("---")
    st.subheader("🤖 Negotiation assistant")

    offer = st.number_input(
        "Current offer ₹",
        min_value=0.0,
        value=float(listing.get("price", 0) or 0),
        step=50.0,
        key=f"offer_{selected['id']}",
    )

    if st.button("Suggest a counter / opening offer", key=f"negotiate_{selected['id']}"):
        suggestion = negotiation_suggestion(
            role=role,
            title=listing.get("title", "Item"),
            listing_price=float(listing.get("price", 0) or 0),
            offer=float(offer),
            price_floor=float(listing.get("price_floor", 0))
            if role == "seller" and listing.get("price_floor") is not None
            else None,
            condition=listing.get("condition", "Good"),
        )
        st.info(suggestion)


# ------------------------------------------------------------
# My Listings
# ------------------------------------------------------------
def my_listings_page():
    st.markdown("<div class='market-title'>📦 My Listings</div>", unsafe_allow_html=True)
    client = db_required()
    mine = safe_execute(
        lambda: client.table("listings")
        .select("*")
        .eq("seller_id", USER_ID)
        .order("created_at", desc=True)
        .execute(),
        [],
    )

    if not mine:
        st.info("You have not listed anything yet.")
        return

    for item in mine:
        listing_card(item)

        if item.get("status", "active") == "active":
            convs = safe_execute(
                lambda: client.table("conversations")
                .select("id,buyer_id")
                .eq("listing_id", item["id"])
                .execute(),
                [],
            )

            buyer_ids = [c["buyer_id"] for c in convs]
            buyer_map = {}
            if buyer_ids:
                buyers = safe_execute(
                    lambda: client.table("profiles")
                    .select("id,display_name,email")
                    .in_("id", buyer_ids)
                    .execute(),
                    [],
                )
                buyer_map = {
                    b["id"]: f"{b['display_name']} ({b['email']})"
                    for b in buyers
                }

            options = ["Select buyer"] + list(buyer_map.keys())
            selected_buyer = st.selectbox(
                "Buyer / conversation participant",
                options,
                format_func=lambda x: "Select buyer" if x == "Select buyer" else buyer_map[x],
                key=f"buyer_{item['id']}",
            )
            sale_price = st.number_input(
                "Completed sale price ₹",
                min_value=0.0,
                value=float(item.get("price", 0) or 0),
                step=50.0,
                key=f"saleprice_{item['id']}",
            )

            if st.button("Mark sold + record transaction", key=f"sold_{item['id']}"):
                if selected_buyer == "Select buyer":
                    st.error("Select the buyer so the transaction and peer rating can be linked.")
                else:
                    tx = safe_execute(
                        lambda: client.table("transactions")
                        .insert({
                            "listing_id": item["id"],
                            "buyer_id": selected_buyer,
                            "seller_id": USER_ID,
                            "category": item["category"],
                            "item_condition": item["condition"],
                            "original_price": item["original_price"],
                            "listing_price": item["price"],
                            "sale_price": float(sale_price),
                            "status": "completed",
                        })
                        .execute(),
                        [],
                    )
                    if tx:
                        safe_execute(
                            lambda: client.table("listings")
                            .update({"status": "sold"})
                            .eq("id", item["id"])
                            .execute(),
                            [],
                        )
                        cached_transactions.clear()
                        st.success("Transaction recorded and listing marked sold.")
                        st.rerun()


# ------------------------------------------------------------
# Watchlist
# ------------------------------------------------------------
def watchlist_page():
    st.markdown("<div class='market-title'>⭐ Watchlist</div>", unsafe_allow_html=True)
    client = db_required()

    rows = safe_execute(
        lambda: client.table("watchlists")
        .select("listing_id")
        .eq("user_id", USER_ID)
        .order("created_at", desc=True)
        .execute(),
        [],
    )
    ids = [r["listing_id"] for r in rows]
    if not ids:
        st.info("Your watchlist is empty.")
        return

    listings = safe_execute(
        lambda: client.table("listings")
        .select("*")
        .in_("id", ids)
        .order("created_at", desc=True)
        .execute(),
        [],
    )
    for item in listings:
        if item.get("status", "active") == "active":
            listing_card(item)


# ------------------------------------------------------------
# Profile + transactions + ratings
# ------------------------------------------------------------
def profile_page():
    st.markdown("<div class='market-title'>👤 My IBS Profile</div>", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    ratings_received = safe_execute(
        lambda: db_required().table("ratings")
        .select("score")
        .eq("to_user_id", USER_ID)
        .execute(),
        [],
    )
    avg_rating = (
        sum(float(x["score"]) for x in ratings_received) / len(ratings_received)
        if ratings_received else 0
    )

    c1.metric("Campus rating", f"{avg_rating:.1f}/5" if ratings_received else "New")
    c2.metric("Ratings received", len(ratings_received))
    c3.metric("Campus domain", "@ibsindia.org")

    st.markdown("---")
    st.subheader("Completed transactions")

    client = db_required()
    txs = safe_execute(
        lambda: client.table("transactions")
        .select("*")
        .or_(f"buyer_id.eq.{USER_ID},seller_id.eq.{USER_ID}")
        .order("completed_at", desc=True)
        .execute(),
        [],
    )

    if not txs:
        st.info("Completed transactions will appear here after a listing is marked sold.")
        return

    other_ids = set()
    for tx in txs:
        other_ids.add(tx["seller_id"] if tx["buyer_id"] == USER_ID else tx["buyer_id"])

    profiles = safe_execute(
        lambda: client.table("profiles")
        .select("id,display_name,email")
        .in_("id", list(other_ids))
        .execute(),
        [],
    )
    person_map = {p["id"]: p for p in profiles}

    existing_ratings = safe_execute(
        lambda: client.table("ratings")
        .select("transaction_id")
        .eq("from_user_id", USER_ID)
        .execute(),
        [],
    )
    rated_tx = {x["transaction_id"] for x in existing_ratings}

    for tx in txs:
        other_id = tx["seller_id"] if tx["buyer_id"] == USER_ID else tx["buyer_id"]
        other = person_map.get(other_id, {"display_name": "Campus peer", "email": ""})

        with st.container(border=True):
            st.markdown(f"**{other['display_name']}**")
            st.caption(
                f"{tx['category']} • {tx['item_condition']} • "
                f"Sale ₹{float(tx['sale_price']):,.0f}"
            )

            if tx["id"] not in rated_tx:
                score = st.slider(
                    "Rate this peer",
                    min_value=1,
                    max_value=5,
                    value=5,
                    key=f"score_{tx['id']}",
                )
                comment = st.text_area(
                    "Comment (optional)",
                    key=f"comment_{tx['id']}",
                    max_chars=500,
                )
                if st.button("Submit rating", key=f"rate_{tx['id']}"):
                    created = safe_execute(
                        lambda: client.table("ratings")
                        .insert({
                            "transaction_id": tx["id"],
                            "from_user_id": USER_ID,
                            "to_user_id": other_id,
                            "score": int(score),
                            "comment": comment.strip()[:500],
                        })
                        .execute(),
                        [],
                    )
                    if created:
                        st.success("Rating submitted.")
                        st.rerun()
            else:
                st.success("You rated this transaction.")


# ------------------------------------------------------------
# Navigation
# ------------------------------------------------------------
if nav == "Browse":
    browse_page()
elif nav == "Visual Search":
    visual_search_page()
elif nav == "Sell an Item":
    sell_page()
elif nav == "Chats":
    chats_page()
elif nav == "My Listings":
    my_listings_page()
elif nav == "Watchlist":
    watchlist_page()
elif nav == "Profile":
    profile_page()

st.markdown("---")
st.caption(
    "IBS Marketplace • Campus-only peer-to-peer marketplace • "
    "Google OIDC restricted to @ibsindia.org • AI features are optional and configurable"
)
