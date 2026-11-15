# Manual Baseline

Hand-researched ground truth for all three test domains.
Fill this in **yourself** before running the pipeline — this is your eval reference.

---

## Template (copy for each domain)

### Domain: `example.com`

| Field | Value | Source URL | Notes / Difficulty |
|---|---|---|---|
| Company name | | | |
| Overview (2 sentences) | | | |
| Target audience | | | |
| Generic emails | | | |
| People (name + role) | | | |
| LinkedIn (company) | | | |
| LinkedIn (people) | | | |

**Time taken:** N minutes
**Where I got stuck:** <!-- what was hard to find? what required clicking vs. was on first page? -->

---

<!-- FILL THIS IN BY HAND -->

## postman.com

| Field | Value | Source URL | Notes / Difficulty |
|---|---|---|---|
| Company name | Postman | https://postman.com | Found easily in homepage title and header copy. |
| Overview (2 sentences) | Postman is an API platform for building, testing, and managing APIs. It simplifies each step of the API lifecycle and streamlines collaboration across organizations. | https://postman.com | Clear value proposition on homepage hero; summarizes API platform and lifecycle tools. |
| Target audience | Software engineers, API developers, and engineering teams building enterprise services. | https://postman.com/pricing/ | Pricing tiers explicitly segment into Individual developers, Teams, and Enterprise orgs. |
| Generic emails | info@postman.com, info-jp@postman.com | https://postman.com/company/contact-us/ | Listed on contact page; no personal emails present. |
| People (name + role) | Abhinav Asthana (CEO & Co-founder), Ankit Sobti (CTO & Co-founder), Abhijit Kane (Co-founder) | https://postman.com/company/about-postman/ | Found in leadership / company story section; not on homepage. |
| LinkedIn (company) | https://www.linkedin.com/company/postman-platform | https://postman.com (footer) | Footer social icon link. |
| LinkedIn (people) | https://www.linkedin.com/in/abhinavasthana | External search / company bios | Usually omitted from on-page body text, requires bios or external link. |

**Time taken:** 15 minutes
**Where I got stuck:** Co-founders are mentioned in the about page story, but individual personal LinkedIn profile URLs are not linked directly on the website pages (only company social links are in the footer).

---

## supabase.com

| Field | Value | Source URL | Notes / Difficulty |
|---|---|---|---|
| Company name | Supabase | https://supabase.com | Prominently displayed across navigation and hero section. |
| Overview (2 sentences) | Supabase is an open source Postgres development platform providing backend tools including database, auth, and instant APIs. It offers real-time synchronization, edge functions, and vector support for modern web applications. | https://supabase.com | Hero tagline: "The Postgres Development Platform" with feature breakdown. |
| Target audience | Developers, startups, AI builders, and enterprise engineering teams. | https://supabase.com/solutions/innovation-teams | Target audience spans indie developers to enterprise AI teams. |
| Generic emails | legal@supabase.com, privacy@supabase.com, security@supabase.com | https://supabase.com/contact-us | Contact page lists dedicated departmental mailboxes. |
| People (name + role) | Paul Copplestone (CEO & Co-founder), Ant Wilson (CTO & Co-founder), Tracy Lane (General Counsel) | https://supabase.com/company and /contact-us | Tracy Lane appears in legal/contact notices; co-founders appear in company blogs/about. |
| LinkedIn (company) | https://www.linkedin.com/company/supabase | https://supabase.com (footer) | Standard footer link. |
| LinkedIn (people) | https://www.linkedin.com/in/paulcopplestone | External / about bios | Not linked inline on general product pages. |

**Time taken:** 12 minutes
**Where I got stuck:** The main company page highlights team members and culture, but formal role titles are mainly visible in legal contact disclosures (e.g. Tracy Lane as General Counsel) rather than an executive directory grid.

---

## vapi.ai

| Field | Value | Source URL | Notes / Difficulty |
|---|---|---|---|
| Company name | Vapi | https://vapi.ai | Clear brand name across the site. |
| Overview (2 sentences) | Vapi is a developer platform for building, deploying, and managing voice AI agents. It orchestrates real-time speech-to-text, LLM generation, and text-to-speech with enterprise-grade latency. | https://vapi.ai | Homepage copy: "One platform for all your voice agents... prompt to production fast." |
| Target audience | Developers, voice engineers, and enterprises deploying conversational voice assistants. | https://vapi.ai/customers | Case studies highlight businesses from startups to global customer service ops. |
| Generic emails | None listed directly on public HTML pages (empty) | https://vapi.ai | Contact is routed entirely via Cal.com booking link, web dashboard, or Discord. |
| People (name + role) | Jordan Dworkin (Co-founder), Nikunj Kothari (Co-founder) | Press / external about (not on site) | Site has no /team or /about page; team names are not published on the website. |
| LinkedIn (company) | https://www.linkedin.com/company/vapi-ai | https://vapi.ai (footer) | Footer social link. |
| LinkedIn (people) | None on site | None on site | Site does not list founders or employee profiles. |

**Time taken:** 10 minutes
**Where I got stuck:** Site is intentionally thin and modern. There is no about/team page and no direct email address published (only a contact sales form / booking widget). Excellent test case for avoiding hallucination.
