"""Canonicalize phone numbers and emails to a stable key for identity matching.

A single handle ("+15551234567", "5551234567", "Foo@iCloud.com") must collapse
to ONE key so an inbound message handle resolves to the right contact, and it
must collapse the SAME way every time for the same region.

- Phones go to E.164 via phonenumberslite (pure-Python, offline). The key is
  stored REGARDLESS of validity: gating on is_valid_number() silently drops
  legitimate test/MVNO/short ranges. `region` is the persisted normalization
  region (contract: Region persistence) — a leading '+' overrides it, a bare
  national number depends on it, so the same raw digits key differently under
  different regions. Extensions are dropped (E.164 carries none).
- Emails are NFC + trim + lowercase only. We deliberately do NOT apply Gmail
  dot/plus folding: that is a gmail.com-only rule and would false-merge distinct
  iCloud/custom-domain addresses. canon_email is a normalizer, not a validator.
"""
from __future__ import annotations

import re
import unicodedata

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, shortnumberinfo


def canon_email(raw: str) -> str:
    return unicodedata.normalize("NFC", raw or "").strip().lower()


def canon_phone(raw: str, region: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        n = phonenumbers.parse(raw, region)
    except NumberParseException:
        digits = re.sub(r"\D", "", raw)
        return {"normalized": digits, "kind": "phone", "possible": False} if digits else None
    if shortnumberinfo.is_valid_short_number(n):
        return {"normalized": f"short:{n.national_number}", "kind": "short", "possible": False}
    e164 = phonenumbers.format_number(n, PhoneNumberFormat.E164)
    return {"normalized": e164, "kind": "phone", "possible": phonenumbers.is_possible_number(n)}


def canon_handle(raw: str, region: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if "@" in raw:
        value = canon_email(raw)
        return {"normalized": value, "kind": "email", "possible": True} if value else None
    return canon_phone(raw, region)
