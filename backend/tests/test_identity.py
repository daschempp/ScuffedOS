from app.identity import canon_email, canon_handle, canon_phone


# ---- phones: national variants collapse to one E.164 key ----------------------
def test_phone_national_variants_collapse_to_one_e164_key():
    for raw in ["+15551234567", "5551234567", "(555) 123-4567",
                "1-555-123-4567", "555.123.4567", " 555 123 4567 "]:
        assert canon_phone(raw, "US")["normalized"] == "+15551234567"


def test_duplicate_phone_spellings_produce_one_key():
    # A person listing the same number twice, formatted differently, indexes once.
    keys = {canon_phone(r, "US")["normalized"]
            for r in ["(555) 123-4567", "555-123-4567", "+1 555 123 4567"]}
    assert keys == {"+15551234567"}


def test_phone_keyed_even_when_not_strictly_valid():
    # 555 test range: "possible" but not "valid" -- we must still key it, not drop it.
    r = canon_phone("5551234567", "US")
    assert r["normalized"] == "+15551234567"
    assert r["kind"] == "phone"
    assert r["possible"] is True


# ---- international vs national: '+' carries the country code, region is a fallback
def test_plus_prefixed_ignores_region_but_national_needs_it():
    # With a leading '+', the country code wins and the region argument is irrelevant.
    assert canon_phone("+442083661177", "US")["normalized"] == "+442083661177"
    # The SAME subscriber number in national form only resolves with the right region.
    assert canon_phone("020 8366 1177", "GB")["normalized"] == "+442083661177"


# ---- region CHANGE: identical raw digits canonicalize differently per region ---
def test_same_raw_number_canonicalizes_differently_under_different_regions():
    us = canon_phone("2025550173", "US")
    gb = canon_phone("2025550173", "GB")
    assert us["normalized"] == "+12025550173"          # +1 (NANP)
    assert gb["normalized"] == "+442025550173"         # +44 (GB)
    assert us["normalized"] != gb["normalized"]         # region is load-bearing


def test_region_change_does_not_reinterpret_as_us():
    # Prove a national GB number is NOT force-parsed as if it were US.
    gb = canon_phone("020 8366 1177", "GB")["normalized"]
    us = canon_phone("020 8366 1177", "US")
    assert gb == "+442083661177"
    assert us is None or us["normalized"] != gb


# ---- extensions & malformed numbers -------------------------------------------
def test_extension_is_stripped_from_the_e164_key():
    # E.164 has no extension; the same subscriber number keys once, ext and all.
    assert canon_phone("(555) 123-4567 ext. 890", "US")["normalized"] == "+15551234567"
    assert canon_phone("5551234567x123", "US")["normalized"] == "+15551234567"


def test_short_code():
    r = canon_phone("611", "US")
    assert r["kind"] == "short"
    assert r["normalized"] == "short:611"
    assert r["possible"] is False


def test_unparseable_phone_falls_back_to_digits_or_none():
    # Garbage with no digits is not keyable.
    assert canon_phone("not a phone", "US") is None
    assert canon_phone("", "US") is None
    assert canon_phone("   ", "US") is None
    # Malformed input that phonenumbers rejects but that still carries digits
    # keeps the raw digits so it can be matched later (never silently dropped).
    r = canon_phone("#$%1234%$#", "US")
    assert r is not None and r["kind"] == "phone" and r["possible"] is False
    assert r["normalized"] == "1234"


# ---- emails: NFC + trim + lowercase, NO gmail dot/plus folding -----------------
def test_email_lowercased_trimmed_no_dot_folding():
    assert canon_email("  Foo@iCloud.com ") == "foo@icloud.com"
    # Dots are significant everywhere except gmail -- do NOT strip them.
    assert canon_email("f.o.o@icloud.com") == "f.o.o@icloud.com"
    # '+tag' is significant on non-gmail domains -- do NOT strip it.
    assert canon_email("Jane+news@fastmail.com") == "jane+news@fastmail.com"


def test_email_unicode_is_nfc_normalized():
    # Build the two byte-distinct spellings explicitly (\u escapes) so the
    # test proves NFC folding rather than however the file encodes the accented char.
    decomposed = "cafe\u0301@example.com"  # e + U+0301 combining acute
    composed = "caf\u00e9@example.com"     # single precomposed e + U+00E9 (e-acute)
    assert decomposed != composed             # genuinely different byte strings
    assert canon_email(decomposed) == canon_email(composed)  # both fold to one key


def test_email_is_not_a_validator_and_never_raises():
    # canon_email normalizes; it does not judge. Malformed input must not crash.
    assert canon_email("@@@") == "@@@"
    assert canon_email("") == ""
    assert canon_email("   ") == ""


# ---- canon_handle dispatch + whitespace-only -> None --------------------------
def test_canon_handle_dispatch():
    assert canon_handle("foo@icloud.com", "US")["kind"] == "email"
    assert canon_handle("+15551234567", "US")["kind"] == "phone"
    assert canon_handle("611", "US")["kind"] == "short"


def test_canon_handle_whitespace_only_is_none():
    assert canon_handle("", "US") is None
    assert canon_handle("   ", "US") is None
    assert canon_handle("\t\n ", "US") is None


def test_canon_handle_is_pure_and_shared_handle_is_deterministic():
    # Two different people carrying the SAME handle must produce IDENTICAL keys so
    # resolve_handle later maps both to one normalized value.
    a = canon_handle("Shared@iCloud.com", "US")
    b = canon_handle("shared@icloud.com", "US")
    assert a == b                                   # same key for both people
    assert canon_handle("+1 (555) 000-1111", "US") == canon_handle("5550001111", "US")
