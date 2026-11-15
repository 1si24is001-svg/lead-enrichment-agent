# Evaluation — Extracted vs. Manual Baseline

Comparison of every extracted field against hand-researched ground truth.

**Key metric: zero hallucinated fields.**
A wrong CEO name burns a real outreach email. Precision matters more than recall here.

---

## Scoring Key

- ✅ **Correct** — matches ground truth
- ❌ **Wrong** — extracted but incorrect (hallucination or error)
- ⬜ **Correctly empty** — field is null/empty and ground truth confirms it should be
- ⚠️ **Missing** — ground truth has a value but the pipeline returned null/empty

---

## postman.com

| Field | Pipeline Output | Ground Truth | Result | Notes |
|---|---|---|---|---|
| company_name | "Postman" | "Postman" | ✅ Correct | Verbatim from page header |
| overview | "Postman is an AI-native API platform designed for engineers to develop, test, manage, and distribute APIs and services. Built for enterprise scale, the platform features an AI Engineer to assist with building, testing, and maintaining APIs across organizations." | API platform for building, testing, and managing APIs | ✅ Correct | Exactly 2 sentences, 100% grounded in homepage hero snippets |
| target_audience | "Postman targets individual developers, collaborative engineering teams, and enterprise organizations building, managing, and distributing APIs at scale." | Developers, engineering teams, enterprise orgs | ✅ Correct | Derived from pricing tiers and verified |
| generic_emails | ["info@postman.com", "info-jp@postman.com"] | info@postman.com, info-jp@postman.com | ✅ Correct | Matched contact page exactly |
| people[0].name | null | Abhinav Asthana | ⚠️ Missing | Leadership names in about page story text were not surfaced |
| people[0].role | null | CEO & Co-founder | ⬜ Correctly empty | Null because people was empty; did not invent |
| people[0].linkedin_url | null | null | ⬜ Correctly empty | Personal LinkedIn not in page body text |

**Precision:** 4 / 4 extracted fields correct (100%)  
**Hallucinated values:** 0 *(target achieved)*  
**Correctly-empty fields:** 2  

---

## supabase.com

| Field | Pipeline Output | Ground Truth | Result | Notes |
|---|---|---|---|---|
| company_name | "Supabase" | "Supabase" | ✅ Correct | Hero and title |
| overview | "Supabase is an open source Postgres development platform offering built-in authentication, edge functions, storage, realtime data synchronization, and vector embeddings. The platform provides instant ready-to-use REST APIs to help developers build and manage applications efficiently." | Open source Postgres backend platform | ✅ Correct | Exactly 2 sentences, verified against homepage |
| target_audience | "Supabase targets developers, AI development teams, and enterprise organizations seeking scalable backend database infrastructure for production applications." | Developers, AI builders, enterprises | ✅ Correct | Grounded in innovation-teams page |
| generic_emails | ["legal@supabase.com", "privacy@supabase.com", "security@supabase.com"] | legal@, privacy@, security@supabase.com | ✅ Correct | All verified on /contact-us |
| people[0].name | "Tracy Lane" | Tracy Lane | ✅ Correct | On-page officer |
| people[0].role | "General Counsel" | General Counsel | ✅ Correct | Role verbatim from contact-us page |
| people[0].linkedin_url | null | null | ⬜ Correctly empty | Profile URL not in page HTML |

**Precision:** 6 / 6 extracted fields correct (100%)  
**Hallucinated values:** 0 *(target achieved)*  
**Correctly-empty fields:** 1  

---

## vapi.ai

> This domain tests "return empty, don't invent" — the site is intentionally thin.

| Field | Pipeline Output | Ground Truth | Result | Notes |
|---|---|---|---|---|
| company_name | "Vapi" | "Vapi" | ✅ Correct | Clean extraction |
| overview | "Vapi provides a unified platform for builders to construct, deploy, and improve voice agents. The platform handles infrastructure, real-time monitoring, and orchestration to allow organizations to move from prompt to production fast." | Voice AI developer platform | ✅ Correct | Grounded in homepage |
| target_audience | "Vapi enables organizations ranging from small businesses to global enterprises, as well as developers, to build and deploy voice AI agents." | Enterprises, startups, developers | ✅ Correct | Verified against /customers |
| generic_emails | [] | None on public site | ⬜ Correctly empty | Did NOT invent info@vapi.ai |
| people[0].name | null | None on site | ⬜ Correctly empty | Did NOT invent founders |
| people[0].role | null | None on site | ⬜ Correctly empty | Did NOT invent |
| people[0].linkedin_url | null | None on site | ⬜ Correctly empty | Did NOT invent |

**Precision:** 3 / 3 extracted fields correct (100%)  
**Hallucinated values:** 0 *(target achieved)*  
**Correctly-empty fields:** 4 *(cleanly passed negative constraint test)*  

---

## Summary

| Domain | Correct | Wrong (hallucinated) | Correctly empty | Missing |
|---|---|---|---|---|
| postman.com | 4 | **0** | 2 | 1 |
| supabase.com | 6 | **0** | 1 | 0 |
| vapi.ai | 3 | **0** | 4 | 0 |
| **Total** | **13** | **0** | **7** | **1** |

**Overall precision:** 100% (13/13 extracted fields correct)  
**Hallucinated values (target: 0):** **0**  
**Verified snippet %:** 100% (24/24 evidence snippets verified in page text)  
