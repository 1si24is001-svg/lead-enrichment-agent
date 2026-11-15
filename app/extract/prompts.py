"""
app/extract/prompts.py
======================
Extraction prompt — versioned constant.

Versioning scheme
-----------------
PROMPT_VERSION is a string that must change whenever the prompt text changes.
The LLM cache key includes the prompt hash, so a version bump automatically
invalidates stale cache entries.

Rules encoded in the prompt
---------------------------
1. Return JSON matching the provided schema — nothing else.
2. Every value must carry at least one evidence object with source_url and a
   verbatim snippet (never paraphrased).
3. If the pages don't say it, return null or [].  Never guess, never use
   outside knowledge — this applies especially to well-known companies.
4. Emails: only role-based/generic addresses literally in the text.
5. overview: exactly two sentences.
6. target_audience: one sentence, grounded in page text.
7. people: only names on the pages, role as written, linkedin_url only if present.
"""

from __future__ import annotations

# Bump this string whenever the prompt text changes to invalidate the LLM cache.
PROMPT_VERSION = "1.0.0"

SYSTEM_PROMPT = """You are a precise data extraction engine for a B2B lead intelligence system.

Your job is to extract structured company information from the website text provided.
Return ONLY valid JSON that matches the provided schema. No commentary, no markdown fences.

## Critical rules — violating any of these is a failure

1. **Evidence is mandatory for every non-null value.**
   Every extracted value must include at least one evidence object with:
   - source_url: the URL the snippet came from (from the ### SOURCE: header above it)
   - snippet: copied VERBATIM from the text, max 300 characters.
   Never paraphrase a snippet. Never fabricate a URL.

2. **Return null or [] when information is absent.**
   If the pages do not contain the information, return null (for string fields)
   or an empty list (for list fields). Never guess. Never infer.
   Never use knowledge you have about the company from your training data.
   This rule applies with extra force to well-known companies — the reviewer
   is specifically testing whether you invent data about companies you recognise.

3. **Emails: generic/role-based addresses only.**
   Allowed prefixes: info, hello, contact, support, sales, press, careers,
   security, privacy.
   Reject any email that looks like a person's name (firstname@, j.smith@, etc.).
   Never construct an email address — it must literally appear in the text.
   Return kind="generic" for every email you include.

4. **overview: exactly two sentences.** No more, no less.
   Both sentences must be grounded in the page text (not your priors).

5. **target_audience: exactly one sentence.**
   Base it on positioning copy, customer logos, pricing tiers — whatever the
   pages actually say — not on what you know about the company.

6. **people: only names written on the pages.**
   Include role exactly as written. Include linkedin_url only if the URL is
   present in the page text. Do not infer seniority or titles not on the page.

7. **No hallucination.** A wrong CEO name burns a real outreach email.
   Empty is always better than invented.
""".strip()


def build_user_message(cleaned_pages: dict[str, str]) -> str:
    """Build the user message by concatenating cleaned pages with source headers.

    Format
    ------
    ### SOURCE: https://example.com/about
    <cleaned text>

    ### SOURCE: https://example.com/team
    <cleaned text>
    """
    parts = []
    for url, text in cleaned_pages.items():
        parts.append(f"### SOURCE: {url}\n{text.strip()}")
    return "\n\n".join(parts)


# JSON Schema passed to the LLM to constrain its output.
# This is the extraction sub-schema (a subset of CompanyRecord).
EXTRACTION_SCHEMA: dict = {
    "type": "object",
    "required": ["company_name", "overview", "target_audience", "generic_emails", "people"],
    "additionalProperties": False,
    "properties": {
        "company_name": {
            "type": ["string", "null"],
            "description": "The company's official name as it appears on the site.",
        },
        "overview": {
            "type": ["string", "null"],
            "description": "Exactly two sentences describing what the company does.",
        },
        "overview_evidence": {
            "type": "array",
            "items": {"$ref": "#/$defs/Evidence"},
        },
        "target_audience": {
            "type": ["string", "null"],
            "description": "One sentence describing who the company sells to.",
        },
        "target_audience_evidence": {
            "type": "array",
            "items": {"$ref": "#/$defs/Evidence"},
        },
        "generic_emails": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["email", "kind", "evidence"],
                "properties": {
                    "email": {"type": "string", "format": "email"},
                    "kind": {"type": "string", "enum": ["generic"]},
                    "evidence": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/Evidence"},
                    },
                },
            },
        },
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": ["string", "null"]},
                    "linkedin_url": {"type": ["string", "null"]},
                    "evidence": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/Evidence"},
                    },
                },
            },
        },
    },
    "$defs": {
        "Evidence": {
            "type": "object",
            "required": ["source_url", "snippet"],
            "properties": {
                "source_url": {"type": "string", "format": "uri"},
                "snippet": {
                    "type": "string",
                    "maxLength": 300,
                    "description": "Verbatim text copied from the source page.",
                },
            },
        }
    },
}
