# Crisis Detection & Response System

## Overview

DevOps Agent includes a global crisis detection and response system designed to protect user safety and ensure platform liability compliance. When a user mentions suicidal ideation or self-harm, the system:

1. **Detects** the crisis language instantly (milliseconds, zero AI cost)
2. **Logs** the incident to an audit trail for support team review
3. **Shows** a crisis banner with localized resources (phone, chat, website)
4. **Disables** the chat input to prevent continued conversation
5. **Directs** the user to professional mental health support

## Architecture

### Three-Layer Guardrails Stack

```
User Message
    ↓
1. INPUT SANITIZATION (services/input_sanitizer.py)
   - Block SQL/JS injection patterns
   - Enforce length limits
    ↓
2. CRISIS DETECTION (src/agent/guardrails.py)
   - Fast keyword-based detection (FAIL CLOSED)
   - Returns GuardrailResult with is_crisis flag
    ↓
3. SECURITY SCREENING (Haiku semantic + tool safety)
   - AI-powered jailbreak detection
   - Tool call risk classification
    ↓
Agent Response
```

**Key principle:** Crisis detection is separate from policy violations. Crisis incidents are **logged but not flagged as violations**.

### Components

#### 1. Crisis Language Detection
**File:** `src/agent/guardrails.py`

- **Keywords:** 726 crisis-related phrases across 4 severity levels
- **Languages:** English, Spanish, French, German, Italian, etc.
- **Function:** `detect_crisis_language(message: str) → (bool, str, dict)`
  - Returns: `(is_crisis, severity, keywords_matched)`
  - Severity levels: `'high'` (suicide intent), `'medium'` (self-harm), `'low'` (hopelessness)

#### 2. Crisis Resources Service
**File:** `services/crisis_resources.py`

- **30+ countries** with localized hotlines, SMS, chat, and websites
- **Fallback:** International Association for Suicide Prevention (if country unknown)
- **Function:** `get_crisis_resources(country_code: str) → dict`
  - Returns: Resource dict with name, phone, sms, url, url_chat, available_24_7, languages
- **Function:** `get_user_country_from_request(request) → str`
  - Detects country from CloudFlare headers or geo headers
  - Used for automatic resource localization

#### 3. Crisis Incident Model
**File:** `models.py → CrisisIncident`

Audit trail table recording every crisis detection:
- `user_id` (FK to User)
- `message_snippet` (first 500 chars, no full message stored)
- `severity` ('high', 'medium', 'low')
- `crisis_keywords` (JSON: matched keywords + count)
- `action` ('banner_shown', 'escalated', etc.)
- `resources_provided` (JSON: resource dict offered to user)
- `user_country` (inferred from request headers)
- `user_ip`, `user_agent` (for investigation)
- `resolved` (bool, for support team follow-up)
- `support_notes` (for manual intervention records)

#### 4. Chat Route Integration
**File:** `app.py → /api/chat and /api/chat/stream`

When `screen_message()` returns `is_crisis=True`:
- Non-streaming: Return HTTP 200 with `crisis_response: true`
- Streaming (SSE): Emit `{'type': 'crisis', 'resources': {...}}`
- **Do NOT** increment guardrail violation counter
- **DO** create CrisisIncident log entry

#### 5. Frontend Banner
**File:** `templates/index.html`

JavaScript function `showCrisisBanner(resources)`:
- Displays red banner with:
  - Localized organization name
  - Phone number (as tel: link)
  - SMS instructions
  - Chat/website link
  - Emergency services callout
- **Disables** message input
- **Scrolls** banner into view
- **No styling warnings** or error messages

## Supported Countries (30+)

| Code | Organization | Phone |
|------|--------------|-------|
| US | 988 Suicide & Crisis Lifeline | 988 |
| CA | Canada Suicide Prevention Service | 1-833-456-4566 |
| GB | Samaritans | 116-123 |
| IE | Samaritans Ireland | 1800-609-109 |
| FR | SOS Amitié | 09-72-39-40-50 |
| DE | Telefonseelsorge | 0800-111-0111 |
| ES | Telégono de la Esperanza | 024 |
| IT | Telefono Amico | 02-2327-2327 |
| NL | Stichting 113 | 900-0113 |
| BE | Centre de Prévention du Suicide | 02-649-95-55 |
| CH | Die Dargebotene Hand | 143 |
| AT | Telefonseelsorge Österreich | 142 |
| PL | Centrum Zdrowia Psychicznego | 116-123 |
| SE | Nationellt centrum för suicidprevention | 771-481-481 |
| NO | Kirkens SOS | 22-40-00-40 |
| DK | Livslinien | 40-51-44-48 |
| FI | Suomen Mielenterveysseura | 9-2525-0552 |
| AU | Lifeline Australia | 13-11-14 |
| NZ | 1737, Need to Talk? | 1737 |
| IN | AASRA | 22-2772-4030 |
| JP | Inochi no Denwa | 570-783-556 |
| KR | Korea Suicide Prevention Center | 1393 |
| BR | CVV Brasil | 188 |
| MX | Teléfono de la Esperanza | 5255-2592-0500 |
| **NG** | **Lifeline Nigeria** | **+234-9119944357** |
| ZA | Befrienders South Africa | 0861-233-7436 |
| KE | Befrienders Kenya | 722-178-177 |
| MY | Befrienders Malaysia | 03-7627-2929 |
| SG | Samaritans Singapore | 1800-221-4444 |
| PH | In Touch Community Services | 2-8893-7603 |
| TH | Sresoonthorn Institute | 2-352-9090 |
| CN | Beijing Crisis Hotline | 10-8295-1332 |

**Fallback (unknown country):** International Association for Suicide Prevention (https://www.iasp.info/resources/Crisis_Centres/)

## Keyword Coverage

### High Severity (Suicide Intent)
- "suicide", "kill myself", "end my life", "end it all", "take my life"
- Spanish: "suicidio", "quiero suicidarme", "matarme", "terminar mi vida"
- French: "suicide", "me tuer", "finir ma vie"

### Medium Severity (Self-Harm)
- "self-harm", "cutting myself", "hurting myself", "injuring myself"
- Spanish: "automutilación"
- French: "automutilation", "me faire du mal"

### Low Severity (Attempts/Intent)
- "overdose", "hang myself", "slit my wrists", "jump off"
- "won't survive", "no point living", "better off dead"

## Privacy & Compliance

### What We Store
- **Timestamp** of detection
- **First 500 chars** of user message (not full text)
- **Keywords matched** (for analysis)
- **Resources offered** (what was shown to user)
- **User country** (from headers)
- **User IP** (for investigation)

### What We DON'T Store
- Full user message text
- Recording of user interaction after crisis banner
- Any conversation history related to the crisis

### GDPR/CCPA Compliance
- Crisis incident data is classified as **sensitive health information**
- Stored separately from chat history
- Subject to extended retention (audit trail requirement)
- Users have right to request deletion of their crisis incidents

## Testing

Run the crisis detection test suite:

```bash
pytest tests/test_crisis_detection.py -v
```

Tests cover:
- ✅ Language detection (11 tests)
- ✅ Resource lookup (6 tests)
- ✅ HTML banner formatting (3 tests)
- ✅ Guardrail screening (3 tests)
- ✅ Database model (2 tests)

**Coverage:** 25 tests, all passing

## Support Team Workflows

### Accessing Crisis Incidents

Admin endpoint (requires authentication):

```bash
GET /api/admin/crisis-incidents
  ?user_id=123
  &date_from=2026-01-01
  &date_to=2026-01-31
  &severity=high
  &resolved=false
```

Response:
```json
{
  "incidents": [
    {
      "id": 456,
      "user_id": 123,
      "detected_at": "2026-03-25T14:32:00Z",
      "severity": "high",
      "crisis_keywords": {"kill myself": 1},
      "action": "banner_shown",
      "user_country": "US",
      "resolved": false,
      "support_notes": null
    }
  ],
  "total": 42
}
```

### Marking Incidents as Resolved

```bash
PUT /api/admin/crisis-incidents/456
{
  "resolved": true,
  "support_notes": "Contacted user, provided resources, user acknowledged help"
}
```

## Liability Protection

This system demonstrates:

1. **Duty of Care** — Platform actively detects and responds to crisis language
2. **Good Faith Effort** — Resources offered immediately and prominently
3. **Risk Mitigation** — Audit trail showing what happened when
4. **Regulatory Compliance** — Aligns with FTC AI transparency expectations

**Not a substitute for:** Licensed mental health services, crisis counselors, emergency response

## Future Enhancements

1. **Crisis Escalation Workflow**
   - Automatic email to support team for high-severity incidents
   - Escalation to emergency services in specific scenarios

2. **Multi-Language Support**
   - Expand keyword list for additional languages
   - Detect crisis in user's preferred language

3. **Follow-Up System**
   - Automated follow-up email 24 hours later
   - Resource guides specific to country/situation

4. **Analytics Dashboard**
   - Crisis detection trends
   - Geographic hotspots
   - Resource effectiveness tracking

## Related Documentation

- [CLAUDE.md](CLAUDE.md) — Full project context
- [CLAUDE_RUNBOOK.md](CLAUDE_RUNBOOK.md) — Historical fixes and gotchas
- [tests/test_crisis_detection.py](tests/test_crisis_detection.py) — Test suite
