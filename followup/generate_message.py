"""
followup/generate_message.py
------------------------------
Module 2: Generate follow-up communication drafts.

For each high-priority signal, generates a professional message
to healthcare professionals requesting missing information.

These are DRAFTS — a human reviewer approves before sending.
The system never sends messages automatically.
"""

import json
import hashlib
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import GROQ_API_KEY, GROQ_MODEL

CACHE_DIR = Path("cache/llm")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _call_llm(prompt, system_prompt=""):
    """Cached Groq LLM call."""
    raw = system_prompt + prompt
    h = hashlib.md5(raw.encode()).hexdigest()
    cache_path = CACHE_DIR / f"fu_{h}.json"

    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)["response"]

    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=500,
        )
        response = completion.choices[0].message.content

        with open(cache_path, "w") as f:
            json.dump({"response": response}, f, indent=2)

        return response
    except Exception as e:
        print(f"  [!] LLM error: {e}")
        return None


SYSTEM_PROMPT = """You are a pharmacovigilance coordinator drafting follow-up requests
to healthcare professionals. Be professional, concise, and specific about
what information is needed and why. Never be alarmist."""


def generate_followup_message(priority_item, missing_fields=None):
    """
    Generate a follow-up message for a high-priority signal.

    Args:
        priority_item: dict from score_priority.py
        missing_fields: list of specific missing data points
                       (e.g., ["outcome", "dose at event", "time to onset"])

    Returns:
        dict with subject, body, urgency
    """
    drug = priority_item.get("drug", "Unknown")
    event = priority_item.get("event", "Unknown")
    tier = priority_item.get("priority_tier", "MEDIUM")
    prr = priority_item.get("prr", 0)

    if not missing_fields:
        missing_fields = ["patient outcome", "dose at time of event",
                         "time from drug start to event onset",
                         "concomitant medications", "relevant lab values"]

    missing_str = ", ".join(missing_fields)

    prompt = f"""Draft a follow-up request for a healthcare professional about an adverse event report.

Drug: {drug}
Reported event: {event}
Priority: {tier}
Statistical signal strength: PRR = {prr}
Missing information: {missing_str}

Requirements:
- Professional tone, 3-4 sentences maximum
- Explain briefly why this follow-up matters
- List the specific missing data points needed
- Do NOT be alarmist or suggest the drug caused the event

Return as JSON:
{{
  "subject": "Follow-up request subject line",
  "body": "The full message text",
  "urgency": "routine" or "priority" or "urgent"
}}"""

    response = _call_llm(prompt, SYSTEM_PROMPT)
    if not response:
        return {
            "subject": f"Follow-up: {drug} — {event}",
            "body": f"Additional information requested regarding {event} report with {drug}. "
                    f"Missing: {missing_str}.",
            "urgency": "routine",
        }

    try:
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
            clean = clean.rsplit("```", 1)[0]
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "subject": f"Follow-up: {drug} — {event}",
            "body": response[:500],
            "urgency": "routine",
        }


def generate_batch_messages(priority_list, max_messages=5):
    """
    Generate follow-up messages for top priority signals.

    Returns list of message dicts.
    """
    messages = []
    for item in priority_list[:max_messages]:
        print(f"  Generating message: {item['drug']} + {item['event']}...")
        msg = generate_followup_message(item)
        msg["drug"] = item["drug"]
        msg["event"] = item["event"]
        msg["priority_tier"] = item["priority_tier"]
        msg["priority_score"] = item["priority_score"]
        messages.append(msg)

    return messages


def print_followup_messages(messages):
    """Pretty-print generated follow-up messages."""
    print(f"\n{'='*65}")
    print(f"FOLLOW-UP MESSAGES ({len(messages)} generated)")
    print(f"{'='*65}")

    for i, msg in enumerate(messages, 1):
        print(f"\n  --- Message {i} [{msg.get('urgency', '?').upper()}] ---")
        print(f"  Drug: {msg.get('drug')} | Event: {msg.get('event')}")
        print(f"  Priority: {msg.get('priority_tier')} (score: {msg.get('priority_score')})")
        print(f"  Subject: {msg.get('subject', 'N/A')}")
        print(f"  Body: {msg.get('body', 'N/A')}")


# ── Test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing followup/generate_message.py\n")

    test_items = [
        {
            "drug": "rosiglitazone", "event": "Myocardial infarction",
            "priority_tier": "CRITICAL", "priority_score": 12.5, "prr": 24.8,
        },
        {
            "drug": "ciprofloxacin", "event": "Tendon rupture",
            "priority_tier": "HIGH", "priority_score": 8.2, "prr": 8.7,
        },
    ]

    messages = generate_batch_messages(test_items, max_messages=2)
    print_followup_messages(messages)

    print("\n✓ generate_message.py working")
