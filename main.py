"""
Vera Bot — magicpin AI Challenge submission
Implements all 5 required endpoints with Claude-powered message composition.
"""

import os, time, uuid, json, logging, asyncio
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vera-bot")

app = FastAPI(title="Vera Bot", version="1.0.0")

START_TIME = time.time()

# ── In-memory stores ──────────────────────────────────────────────────────────
# (scope, context_id) -> {version, payload}
contexts: dict[tuple[str, str], dict] = {}
# conversation_id -> [{"from": role, "body": text, "ts": iso, "turn": int}]
conversations: dict[str, list] = {}
# suppression: suppression_key -> bool (already sent this run)
suppression_sent: set[str] = set()
# conversation metadata: conv_id -> {merchant_id, customer_id, trigger_id, turns_sent}
conv_meta: dict[str, dict] = {}

VALID_SCOPES = {"category", "merchant", "customer", "trigger"}

# ── Gemini (free tier) ────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_URL     = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + GEMINI_MODEL + ":generateContent"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def count_by_scope() -> dict:
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _) in contexts:
        counts[scope] = counts.get(scope, 0) + 1
    return counts

def get_ctx(scope: str, ctx_id: str) -> Optional[dict]:
    entry = contexts.get((scope, ctx_id))
    return entry["payload"] if entry else None

def detect_auto_reply(message: str, history: list) -> bool:
    """Detect WhatsApp Business canned auto-reply."""
    AUTO_PATTERNS = [
        "automated assistant", "thank you for contacting", "aapki madad ke liye shukriya",
        "bahut-bahut shukriya", "hamari team tak pahuncha", "I am not available",
        "will get back to you", "out of office", "currently unavailable",
    ]
    msg_lower = message.lower()
    if any(p.lower() in msg_lower for p in AUTO_PATTERNS):
        return True
    # Same message 2+ times in history
    if history:
        same = sum(1 for h in history if h.get("body", "").strip() == message.strip())
        if same >= 2:
            return True
    return False

def detect_stop_intent(message: str) -> bool:
    STOP_WORDS = [
        "not interested", "stop", "band karo", "nahi chahiye", "mat bhejo",
        "no thanks", "unsubscribe", "please stop", "don't message", "dnd",
        "not now", "baad mein", "abhi nahi",
    ]
    msg_lower = message.lower()
    return any(w in msg_lower for w in STOP_WORDS)

def detect_accept_intent(message: str) -> bool:
    ACCEPT_WORDS = [
        "yes", "ok", "okay", "sure", "haan", "ha", "let's do it", "go ahead",
        "kar do", "send me", "bhejo", "proceed", "sounds good", "great", "perfect",
        "chalega", "done", "agreed", "confirm",
    ]
    msg_lower = message.lower()
    return any(w in msg_lower for w in ACCEPT_WORDS)

# ── Claude composition ────────────────────────────────────────────────────────

async def call_claude(system: str, user: str, max_tokens: int = 800) -> str:
    """Call Gemini API (free tier)."""
    url = GEMINI_URL + f"?key={GEMINI_API_KEY}"
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": max_tokens,
        },
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=body, headers={"Content-Type": "application/json"})
        r.raise_for_status()
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

COMPOSE_SYSTEM = """You are Vera, magicpin's AI merchant assistant. You compose WhatsApp messages for merchants on the magicpin platform.

RULES:
1. Match the merchant's language preference (hi-en mix if languages include "hi", pure English otherwise).
2. Use peer/collegial tone — not promotional. Clinical vocabulary OK for dentists/pharmacies.
3. NO taboo words: "guaranteed", "100% safe", "cure", "best in city", "miracle".
4. Anchor on ONE concrete, verifiable fact from the context (number, date, stat, headline, source).
5. Single CTA at the end: binary YES/STOP for action triggers; open-ended question for info triggers; none for pure info.
6. Keep it concise — 3–6 sentences max. No long preamble.
7. No fake data. Only use what's in the context.
8. Do NOT re-introduce yourself if this is a follow-up message.
9. Service+price format beats percentage discounts: "Haircut @ ₹99" > "10% off".
10. Use one compulsion lever: specificity, loss aversion, social proof, effort externalization, curiosity, or binary commitment.

TRIGGER-SPECIFIC GUIDANCE:
- research_digest → cite source + trial size + specific finding; offer to pull/share content
- perf_dip → name the exact metric and drop %; offer one concrete fix
- perf_spike → celebrate + curiosity hook about what drove it
- renewal_due → name exact days + plan + renewal amount; use loss aversion
- recall_due (customer) → name the service due, available slots, price; send_as=merchant_on_behalf
- festival_upcoming → tie festival timing to specific service from catalog
- milestone_reached → celebrate + curiosity about next milestone
- review_theme_emerged → name theme + occurrence count; offer to draft a response
- dormant_with_vera → curious re-engagement question
- regulation_change → name regulation + deadline; offer to help comply
- curious_ask_due → ask one genuine question about the merchant's business this week
- winback_eligible → reference lapsed customers + days since expiry; offer easy re-activation

OUTPUT FORMAT (JSON only, no markdown):
{
  "body": "<the WhatsApp message body>",
  "cta": "open_ended" | "binary_yes_stop" | "none",
  "send_as": "vera" | "merchant_on_behalf",
  "suppression_key": "<from trigger or generated>",
  "rationale": "<1-2 sentences: why this message, what lever used>"
}"""

async def compose_message(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
    conversation_history: Optional[list] = None,
) -> dict:
    """Compose a message using Claude."""
    ctx_summary = {
        "category_slug": category.get("slug"),
        "voice_tone": category.get("voice", {}).get("tone"),
        "voice_code_mix": category.get("voice", {}).get("code_mix"),
        "vocab_taboo": category.get("voice", {}).get("vocab_taboo", []),
        "peer_stats": category.get("peer_stats", {}),
        "offer_catalog": category.get("offer_catalog", [])[:5],
        "digest_top": category.get("digest", [])[:3],
        "seasonal_beats": category.get("seasonal_beats", [])[:2],
    }
    merchant_summary = {
        "merchant_id": merchant.get("merchant_id"),
        "name": merchant.get("identity", {}).get("name"),
        "owner_first_name": merchant.get("identity", {}).get("owner_first_name"),
        "city": merchant.get("identity", {}).get("city"),
        "locality": merchant.get("identity", {}).get("locality"),
        "languages": merchant.get("identity", {}).get("languages", ["en"]),
        "subscription": merchant.get("subscription", {}),
        "performance": merchant.get("performance", {}),
        "offers": [o for o in merchant.get("offers", []) if o.get("status") == "active"],
        "signals": merchant.get("signals", []),
        "customer_aggregate": merchant.get("customer_aggregate", {}),
        "review_themes": merchant.get("review_themes", [])[:3],
        "recent_conversation": (merchant.get("conversation_history") or [])[-3:],
    }
    trigger_summary = {
        "id": trigger.get("id"),
        "kind": trigger.get("kind"),
        "scope": trigger.get("scope"),
        "source": trigger.get("source"),
        "urgency": trigger.get("urgency"),
        "payload": trigger.get("payload", {}),
        "suppression_key": trigger.get("suppression_key", ""),
    }
    customer_summary = None
    if customer:
        customer_summary = {
            "customer_id": customer.get("customer_id"),
            "name": customer.get("identity", {}).get("name"),
            "language_pref": customer.get("identity", {}).get("language_preference"),
            "state": customer.get("state"),
            "relationship": customer.get("relationship", {}),
            "preferences": customer.get("preferences", {}),
        }

    user_prompt = f"""CATEGORY CONTEXT:
{json.dumps(ctx_summary, ensure_ascii=False, indent=2)}

MERCHANT CONTEXT:
{json.dumps(merchant_summary, ensure_ascii=False, indent=2)}

TRIGGER:
{json.dumps(trigger_summary, ensure_ascii=False, indent=2)}
"""
    if customer_summary:
        user_prompt += f"""
CUSTOMER CONTEXT (send_as = merchant_on_behalf):
{json.dumps(customer_summary, ensure_ascii=False, indent=2)}
"""
    if conversation_history:
        user_prompt += f"""
CONVERSATION SO FAR (do not repeat what was said):
{json.dumps(conversation_history[-4:], ensure_ascii=False, indent=2)}
"""
    user_prompt += "\nCompose the next message. Return JSON only."

    raw = await call_claude(COMPOSE_SYSTEM, user_prompt, max_tokens=600)
    # Strip possible code fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()
    result = json.loads(raw)
    return result

REPLY_SYSTEM = """You are Vera, magicpin's merchant AI assistant. You are mid-conversation with a merchant (or customer).
Decide the next action based on the merchant's latest reply and conversation context.

RULES:
- If merchant accepted/engaged → continue the thread, deliver what was promised, offer next step.
- If merchant asked a question → answer concisely with data from context.
- If message is an auto-reply (detected externally) → try once with a soft re-engage, then end.
- If merchant said stop/not-interested → end gracefully with a friendly note.
- After 3 bot sends with no genuine engagement → end.
- Never repeat the same message body verbatim.
- Keep responses concise (2–4 sentences).
- Match merchant language preference.

OUTPUT FORMAT (JSON only):
{
  "action": "send" | "wait" | "end",
  "body": "<message if action=send, else null>",
  "cta": "open_ended" | "binary_yes_stop" | "none",
  "wait_seconds": <int if action=wait, else null>,
  "rationale": "<why this action>"
}"""

async def compose_reply(
    conversation_id: str,
    merchant_id: str,
    customer_id: Optional[str],
    from_role: str,
    message: str,
    turn_number: int,
) -> dict:
    """Compose a reply to a merchant/customer message."""
    history = conversations.get(conversation_id, [])
    meta = conv_meta.get(conversation_id, {})

    # Quick checks before calling LLM
    is_auto = detect_auto_reply(message, history)
    is_stop = detect_stop_intent(message)

    bot_turns = sum(1 for h in history if h.get("from") == "bot")

    if is_stop:
        return {
            "action": "end",
            "body": None,
            "cta": "none",
            "wait_seconds": None,
            "rationale": "Merchant signaled not interested; exiting gracefully.",
        }
    if bot_turns >= 4 and is_auto:
        return {
            "action": "end",
            "body": None,
            "cta": "none",
            "wait_seconds": None,
            "rationale": "Auto-reply detected repeatedly; exiting to avoid spam.",
        }

    # Get context for this conversation
    merchant = get_ctx("merchant", merchant_id) or {}
    category_slug = merchant.get("category_slug", "")
    category = get_ctx("category", category_slug) or {}
    customer = get_ctx("customer", customer_id) if customer_id else None
    trigger_id = meta.get("trigger_id", "")
    trigger = get_ctx("trigger", trigger_id) or {}

    ctx_info = {
        "merchant_name": merchant.get("identity", {}).get("name", ""),
        "owner_first_name": merchant.get("identity", {}).get("owner_first_name", ""),
        "languages": merchant.get("identity", {}).get("languages", ["en"]),
        "category": category_slug,
        "voice_tone": category.get("voice", {}).get("tone", ""),
        "active_offers": [o for o in merchant.get("offers", []) if o.get("status") == "active"],
        "performance": merchant.get("performance", {}),
        "peer_stats": category.get("peer_stats", {}),
        "digest_top": category.get("digest", [])[:2],
        "signals": merchant.get("signals", []),
        "trigger_kind": trigger.get("kind", ""),
        "trigger_payload": trigger.get("payload", {}),
        "is_auto_reply_detected": is_auto,
        "bot_turns_so_far": bot_turns,
        "customer": {
            "name": customer.get("identity", {}).get("name") if customer else None,
            "state": customer.get("state") if customer else None,
            "relationship": customer.get("relationship", {}) if customer else None,
        } if customer else None,
    }

    user_prompt = f"""CONTEXT:
{json.dumps(ctx_info, ensure_ascii=False, indent=2)}

CONVERSATION HISTORY:
{json.dumps(history[-6:], ensure_ascii=False, indent=2)}

MERCHANT'S LATEST MESSAGE (turn {turn_number}):
"{message}"

Auto-reply detected: {is_auto}
Bot turns sent so far: {bot_turns}

Decide next action. Return JSON only."""

    raw = await call_claude(REPLY_SYSTEM, user_prompt, max_tokens=400)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()
    result = json.loads(raw)
    return result

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/v1/healthz")
async def healthz():
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": count_by_scope(),
    }

@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Vera Enhanced",
        "team_members": ["AI Builder"],
        "model": GEMINI_MODEL,
        "approach": (
            "Claude-powered 4-context composer with trigger-specific prompt routing, "
            "auto-reply detection, intent-transition handling, and multi-turn state management."
        ),
        "contact_email": "team@example.com",
        "version": "1.0.0",
        "submitted_at": "2026-04-30T00:00:00Z",
    }

class ContextBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str

@app.post("/v1/context")
async def push_context(body: ContextBody):
    if body.scope not in VALID_SCOPES:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_scope",
                     "details": f"scope must be one of {sorted(VALID_SCOPES)}"},
        )
    key = (body.scope, body.context_id)
    current = contexts.get(key)
    if current and current["version"] >= body.version:
        return JSONResponse(
            status_code=409,
            content={"accepted": False, "reason": "stale_version",
                     "current_version": current["version"]},
        )
    contexts[key] = {"version": body.version, "payload": body.payload}
    ack_id = f"ack_{body.context_id}_v{body.version}_{uuid.uuid4().hex[:6]}"
    log.info(f"Context stored: scope={body.scope} id={body.context_id} v={body.version}")
    return {"accepted": True, "ack_id": ack_id, "stored_at": now_iso()}

class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = []

@app.post("/v1/tick")
async def tick(body: TickBody):
    actions = []
    tasks = []

    for trg_id in body.available_triggers:
        trg = get_ctx("trigger", trg_id)
        if not trg:
            continue
        # Skip suppressed
        sup_key = trg.get("suppression_key", trg_id)
        if sup_key in suppression_sent:
            continue
        # Skip expired
        expires = trg.get("expires_at", "")
        if expires and expires < body.now:
            continue

        merchant_id = trg.get("merchant_id") or trg.get("payload", {}).get("merchant_id")
        if not merchant_id:
            continue
        merchant = get_ctx("merchant", merchant_id)
        if not merchant:
            continue
        category_slug = merchant.get("category_slug", "")
        category = get_ctx("category", category_slug)
        if not category:
            continue
        customer_id = trg.get("customer_id")
        customer = get_ctx("customer", customer_id) if customer_id else None

        tasks.append((trg_id, trg, merchant, merchant_id, category, customer, customer_id, sup_key))

    # Compose messages concurrently (cap at 10 per tick)
    async def build_action(trg_id, trg, merchant, merchant_id, category, customer, customer_id, sup_key):
        try:
            composed = await compose_message(category, merchant, trg, customer)
            conv_id = f"conv_{merchant_id}_{trg_id}_{uuid.uuid4().hex[:6]}"
            conv_meta[conv_id] = {
                "merchant_id": merchant_id,
                "customer_id": customer_id,
                "trigger_id": trg_id,
            }
            conversations[conv_id] = []
            suppression_sent.add(sup_key)
            return {
                "conversation_id": conv_id,
                "merchant_id": merchant_id,
                "customer_id": customer_id,
                "send_as": composed.get("send_as", "vera"),
                "trigger_id": trg_id,
                "template_name": f"vera_{trg.get('kind', 'generic')}_v1",
                "template_params": [
                    merchant.get("identity", {}).get("owner_first_name", ""),
                    trg.get("kind", ""),
                    composed.get("body", "")[:60],
                ],
                "body": composed.get("body", ""),
                "cta": composed.get("cta", "open_ended"),
                "suppression_key": sup_key,
                "rationale": composed.get("rationale", ""),
            }
        except Exception as e:
            log.error(f"Error composing for trigger {trg_id}: {e}")
            return None

    results = await asyncio.gather(*[
        build_action(*t) for t in tasks[:10]
    ])
    actions = [r for r in results if r]
    log.info(f"Tick at {body.now}: {len(tasks)} triggers → {len(actions)} actions")
    return {"actions": actions}

class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int

@app.post("/v1/reply")
async def reply(body: ReplyBody):
    # Record incoming message
    conv = conversations.setdefault(body.conversation_id, [])
    conv.append({
        "from": body.from_role,
        "body": body.message,
        "ts": body.received_at,
        "turn": body.turn_number,
    })

    merchant_id = body.merchant_id
    customer_id = body.customer_id

    # Fall back to conv_meta
    meta = conv_meta.get(body.conversation_id, {})
    if not merchant_id:
        merchant_id = meta.get("merchant_id")
    if not customer_id:
        customer_id = meta.get("customer_id")

    if not merchant_id:
        return {"action": "end", "body": None, "cta": "none", "wait_seconds": None,
                "rationale": "Unknown merchant; cannot continue."}

    try:
        result = await compose_reply(
            conversation_id=body.conversation_id,
            merchant_id=merchant_id,
            customer_id=customer_id,
            from_role=body.from_role,
            message=body.message,
            turn_number=body.turn_number,
        )
    except Exception as e:
        log.error(f"Reply composition error: {e}")
        result = {
            "action": "end",
            "body": None,
            "cta": "none",
            "wait_seconds": None,
            "rationale": f"Composition error: {str(e)[:100]}",
        }

    # Record bot reply
    if result.get("action") == "send" and result.get("body"):
        conv.append({
            "from": "bot",
            "body": result["body"],
            "ts": now_iso(),
            "turn": body.turn_number + 1,
        })

    log.info(f"Reply to conv {body.conversation_id} turn {body.turn_number}: action={result.get('action')}")
    return result

@app.post("/v1/teardown")
async def teardown():
    """Optional: wipe state after test ends."""
    contexts.clear()
    conversations.clear()
    suppression_sent.clear()
    conv_meta.clear()
    log.info("State wiped via teardown.")
    return {"status": "wiped"}

@app.get("/")
async def root():
    return {"service": "Vera Bot", "version": "1.0.0", "endpoints": [
        "POST /v1/context", "POST /v1/tick", "POST /v1/reply",
        "GET /v1/healthz", "GET /v1/metadata", "POST /v1/teardown (optional)"
    ]}
