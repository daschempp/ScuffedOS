"""Scuffed OS assistant — intent engine.

A faithful server-side port of the prototype's assistant-logic.js: keyword/intent
matching that returns a friendly reply plus an optional "action card". This is a
deterministic mock of the AI backend — perfect for the prototype, and a clean seam
to later swap in a real LLM call (return the same {text, action} shape).
"""
from __future__ import annotations

import re


def clean_title(text: str) -> str:
    t = re.sub(r"^(hey |hi |ok |please |can you |could you |would you |i need to |i want to )+", "", text, flags=re.I)
    t = re.sub(
        r"^(add (a )?(task|reminder|to-?do)( to)?:?\s*|remind me to\s*|create (a )?task( to)?:?\s*|new task:?\s*|to-?do:?\s*|set a reminder to\s*)+",
        "", t, flags=re.I,
    )
    t = re.sub(r"[.?!]+$", "", t).strip()
    return (t[:1].upper() + t[1:]) if t else t


def clean_event(text: str) -> str:
    t = re.sub(r"^(hey |hi |ok |please |can you |could you )+", "", text, flags=re.I)
    t = re.sub(
        r"^(schedule|book|set up|add|create|put in)( a| an| my)?( meeting| event| call| appointment)?( for| with| on| about)?:?\s*",
        "", t, flags=re.I,
    )
    t = re.sub(r"[.?!]+$", "", t).strip()
    return (t[:1].upper() + t[1:]) if t else "New event"


def reply(text: str) -> dict:
    """Return {"text": str, "action": dict | None} for a user message."""
    t = text.lower()

    if re.search(r"plan (my|the) day|my day|what('?s| is) (on |up )?today|^agenda|brief me", t):
        return {
            "text": "Here's your day: <strong>4 tasks</strong>, a design standup at 11:30, and a dentist visit at 4. You're $120 under your dining budget and 410 kcal from your goal. Want me to block focus time this morning?",
            "action": {"icon": "layout-dashboard", "title": "Day planned", "meta": "Focus block held · 9:00–10:30", "cta": "Open home", "screen": "home"},
        }

    # explicit task phrasing wins over category keywords (e.g. "add a task to water the plants")
    if re.search(r"\b(add a task|task to|new task|remind me|to-?do|follow up)\b", t):
        et = clean_title(text)
        return {
            "text": "Done — I've added <strong>" + et + "</strong> to your Tasks for today.",
            "action": {"icon": "circle-check-big", "title": "Added to Tasks", "meta": "Today · tap to set a due date", "cta": "View tasks", "screen": "tasks", "makeTask": et},
        }

    if re.search(r"move|transfer|roll(\s|-)?over|put.*savings|into savings", t) and re.search(r"saving|dining|budget|\$|money", t):
        return {
            "text": "Moved <strong>$120</strong> from Dining to Savings. You're still comfortably on budget for June.",
            "action": {"icon": "wallet", "title": "Transfer complete", "meta": "$120 → Savings", "cta": "View finance", "screen": "finance"},
        }

    if re.search(r"spend|spent|budget|afford|cost|how much|finance|expense", t):
        return {
            "text": "You've spent <strong>$1,840</strong> in June — 12% less than May. Dining is your biggest discretionary category at <strong>$186</strong> of $250.",
            "action": {"icon": "wallet", "title": "June spending", "meta": "$1,840 / $2,400 budget", "cta": "View finance", "screen": "finance"},
        }

    if re.search(r"schedule|meeting|calendar|book|appointment|event|invite", t):
        ev = clean_event(text)
        return {
            "text": "Scheduled <strong>" + ev + "</strong>. I found a free slot tomorrow afternoon and sent the invite.",
            "action": {"icon": "calendar", "title": "Event created", "meta": ev + " · Tue 2:00pm", "cta": "Open calendar", "screen": "calendar"},
        }

    if re.search(r"log|ate|eat|breakfast|lunch|dinner|meal|calorie|protein|snack|water|drank", t):
        return {
            "text": "Logged it. You're at <strong>1,910 kcal</strong> today and <strong>132g</strong> protein — 190 calories from your goal.",
            "action": {"icon": "apple", "title": "Meal logged", "meta": "+220 kcal · 18g protein", "cta": "View nutrition", "screen": "nutrition"},
        }

    if re.search(r"remind|task|to-?do|todo|add|call|email|pay|renew|follow up|pick up|buy|order|book a", t):
        ti = clean_title(text)
        return {
            "text": "Done — I've added <strong>" + ti + "</strong> to your Tasks for today.",
            "action": {"icon": "circle-check-big", "title": "Added to Tasks", "meta": "Today · tap to set a due date", "cta": "View tasks", "screen": "tasks", "makeTask": ti},
        }

    if re.search(r"remember|note|memory|second brain|where did|what did i say", t):
        return {
            "text": "Saved to your second brain. I'll surface it when it's relevant — and you can ask me about it anytime.",
            "action": {"icon": "brain", "title": "Stored in memory", "meta": "Tagged automatically", "cta": "Open brain", "screen": "memory"},
        }

    return {
        "text": "I can manage your tasks, calendar, finances and nutrition, or pull anything from your second brain. Tell me what you'd like — for example, “add a task to call the dentist” or “how much did I spend on dining?”",
        "action": None,
    }
