# Gwin's Readers Club

A Nigeria-focused digital reading community platform — digital library with an in-browser reader, Book of the Month, reviews, community discussion, personal journaling, reading streaks/goals/challenges, certificates, and an admin dashboard.

Stack: **FastAPI (async) + SQLite/SQLAlchemy + JWT auth** on the backend, **HTML/CSS/JS + Bootstrap 5** on the frontend — no build step required.

## Modules included in this build

- User auth (register/login/profile/change password), role-based access: Administrator, Moderator, Mentor, Member
- Digital Library: browse/search/filter by category/author/language, featured & recommended books, favorites
- Online Reader: resume reading, progress %, bookmarks, highlights, search-inside-book, dark mode, adjustable font size
- Book of the Month: admin-published, with reading guide + discussion questions
- Book Reviews: ratings, lessons learned, comments
- Community Discussion: general/book/topic/Q&A/announcement categories, replies, pin/remove moderation
- Personal Reading Journal: reflections, quotes, prayer notes, action plans, weekly reflection prompts (private per user)
- Reading Progress: streaks (auto-calculated), monthly/annual goals (auto-updated on book completion), challenges
- Certificates: auto/manual issuance, downloadable branded PDF
- Notifications: per-user list, unread count, admin broadcast to all members
- Admin Dashboard: platform stats, member management (role changes, removal), Book of the Month publishing, challenge creation, broadcasts
- Campus Reading Clubs: create/join clubs, member lists, club events
- Reading Mentorship: mentor profiles, mentorship requests (send/accept/decline), private Q&A threads
- Live Discussions: scheduled sessions (live chat/audio/webinar/author interview), short-poll chat rooms (3-second refresh — no WebSocket infrastructure required)
- Reading Resources: chapter summaries, study guides, vocabulary lists, author bios, reading/discussion guides — linked to a book or general
- Opportunities Hub: scholarships, internships, competitions, essay contests, conferences, leadership programs, volunteer listings, with deadline tracking
- Online Reader Table of Contents: auto-detected from "Chapter/Part/Day/Lesson" markers in a book's text, with click-to-jump navigation

This build now covers **all 22 SRS modules end-to-end**, both backend and frontend.

## 20 additional features + scalability pass

**Scalability infrastructure:**
1. Pagination (`limit`/`offset`) on the books browse endpoint
2. Database indexes on hot-path columns (books, reading progress, reviews, discussions, notifications)
3. In-process TTL cache for expensive/hot reads (admin stats, Book of the Month)
4. Rate limiting middleware (stricter limits on login/register/password-reset, generous backstop elsewhere)
5. Request logging middleware with request IDs and slow-request flagging

**New features:**
6. Expanded multi-field book search (title/author/description/content) with relevance ordering
7. Global search (`/search.html`) across books, discussions, and resources
8. Password reset flow (`forgot-password.html` / `reset-password.html`) — dev-mode token shown in-app since no SMTP is configured
9. Email verification flow (dev-mode token)
10. Reading leaderboard (top readers by books completed and streak)
11. Custom reading shelves (`shelves.html`) — named book collections beyond Favorites
12. Content reporting + moderator review queue (Report button on reviews/discussions, Reports tab in admin)
13. CSV export of personal reading history
14. Admin audit log (role changes, removals, Book of the Month publishes, moderation actions)
15. Bulk book import via CSV (Admin → Bulk Import tab)
16. Related books shown on book detail (same category)
17. Reading history timeline
18. Direct messaging (`messages.html`)
19. PWA support — installable, offline app-shell caching via `manifest.json` + `sw.js`
20. App-wide dark mode toggle (navbar, persisted in localStorage — not just the reader pane)

Two pre-existing bugs caught and fixed during this pass: certificate PDF download and (new) CSV export were using plain `<a href>` links to authenticated endpoints, which can't carry the JWT bearer header — both now use an authenticated `fetch` + blob download instead.

A third bug, caught after initial testing: the rate limiter originally counted every login attempt — successful or not — against its quota, so logging into several accounts back-to-back (exactly what testing role-based privileges requires) could trip a false "too many requests" error. Fixed so only failed auth attempts count toward the limit — successful logins never do, while brute-force protection against repeated failures still works (verified: 15 successful logins in a row all pass; 10+ failed attempts still get rate-limited).

## 20 more reading-experience features (paginated reader)

The reader (`reader.html`) already paginates the full book text into numbered pages (`Page X of Y`, jump-to-page, two-page spread on wide screens) with a working table of contents, bookmarks, multi-color highlights, session notes, search-inside, text-to-speech, hands-free auto page-turn, focus mode, themes, and reading streak/goal tracking. This pass adds 20 more features on top of that:

1. Tap-to-define dictionary lookup (📘 mode — click any word for its definition, via a free dictionary API)
2. Personal vocabulary list — save looked-up words, click to reveal/hide the definition later
3. Karaoke-style read-aloud — the word currently being spoken is highlighted as text-to-speech plays
4. Edit a highlight's note after the fact
5. Delete a highlight (previously highlights could only be added, never removed)
6. Export all highlights + session notes for a book as a downloadable Markdown file
7. Copy a highlighted quote to the clipboard, pre-formatted for sharing
8. Reading calendar heatmap (📅) — a 12-week GitHub-style grid of pages read per day
9. Per-chapter progress bars in the Table of Contents, based on furthest position reached
10. Quick "jump to chapter" dropdown next to the page indicator (in addition to the TOC sidebar)
11. Multi-match search navigation — ◀ / ▶ step through every match, with the term highlighted on the page
12. Text alignment toggle (left-aligned vs. justified)
13. Word spacing control, including a wider "dyslexia-friendly" option
14. Custom background/text color picker, as a fourth theme option alongside light/sepia/dark
15. Bold-text toggle for extra readability
16. Underline as an alternate annotation style to highlighting (chosen per selection)
17. Bookmark ribbon ticks on the mini-map, so bookmarked spots are visible at a glance
18. Print-friendly export — opens a clean, formatted print view of the full book text
19. Hands-free voice navigation (🎙️ — say "next", "back", or "bookmark" to control the reader)
20. Session summary (📊) — pages turned, minutes spent, and reading pace for the current session, plus a configurable break reminder that gently nudges after 15/30/45 minutes

All of these persist locally per-book (or globally, for vocabulary and the reading calendar) via `localStorage`, except highlight edit/delete which are backed by two new endpoints: `PUT /library/highlights/{id}` and `DELETE /library/highlights/{id}`.

## 20 completeness features (closing gaps in existing modules)

The first two passes above added new capabilities and a new module. This pass adds no new modules and no AI — it goes back through every existing module and closes the edit/delete/manage gaps that were left over from "create only" or "view only" endpoints, so each feature behaves the way people expect a mature app to behave.

1. "Helpful" upvote on reviews (`POST /community/reviews/{id}/helpful`, toggle, one vote per user)
2. Delete a review comment (`DELETE /community/reviews/comments/{id}`, own comment or staff)
3. Edit a discussion reply (`PUT /community/replies/{id}`, was delete-only before)
4. Nested reply-to-reply threading in discussions (`parent_reply_id`, rendered indented in the UI)
5. Edit an existing journal entry (`PUT /journal/{id}`, was create/delete only)
6. Journal search — filter entries by keyword and/or date range, in addition to type
7. Edit or delete a reading club (`PUT`/`DELETE /clubs/{id}`, leader or staff only)
8. Leave a club, and leaders/staff can remove a member (`DELETE /clubs/{id}/leave`, `DELETE /clubs/{id}/members/{user_id}`)
9. Edit or cancel a club event, plus RSVP with a live attendee count
10. Edit or cancel a live session, plus RSVP with a live attendee count and attendee list
11. Either party (not just the mentor) can end an active mentorship
12. Rate & review your mentor after a mentorship ends — shows as an average rating on the mentor's card
13. Delete a direct message (soft-delete on your side only — the other person still sees their copy)
14. Delete a notification, plus per-category mute preferences (a Preferences panel on the Notifications page)
15. Edit a reading goal's target instead of deleting and recreating it
16. Edit a reading resource or opportunity listing (was create/delete only)
17. Save/bookmark an opportunity, track "applied" status, and a "My Saved" filter tab
18. Rename a shelf, and reorder the books on it
19. Admin: CSV export of the member list, plus certificate revoke/reinstate
20. Edit/reschedule an existing Book of the Month entry, plus self-service account deactivation (with a matching reactivate-on-login flow)

New backing tables: `ReviewHelpfulVote`, `ClubEventRSVP`, `LiveSessionRSVP`, `MentorRating`, `NotificationPreference`, `SavedOpportunity`. New columns on existing tables: `is_active` (User), `is_edited`/`parent_reply_id` (DiscussionReply), `updated_at` (JournalEntry), `is_cancelled` (ClubEvent, LiveSession), `deleted_by_sender`/`deleted_by_recipient` (DirectMessage), `position` (ReadingListItem), `revoked`/`revoked_reason` (Certificate). Because these are new columns on tables that already existed in previous demo data, **the SQLite database was reset** — run `python seed.py` again after pulling this build so the schema matches.

## 20 more features — fun & easier reading experience (gamification pass)

The three passes above already made the reader itself extremely dense (dictionary lookup, karaoke TTS, autoscroll, focus mode, calendar heatmap, custom themes, voice nav, print export, session summary, break reminders, sound effects, and more). This pass avoids duplicating any of that and instead adds a shared "engage" layer plus a handful of tightly-integrated reader/dashboard hooks:

**Fun:**
1. Achievement badges (first book, streaks, pages read, night owl/early bird, first review) with unlock toasts — `js/engage.js`
2. XP / reading-level system, shown as a progress bar on the dashboard
3. Downloadable "I finished!" share card (canvas-generated PNG) alongside the existing confetti celebration
4. Chapter-end "did you know" trivia snippets
5. Per-session mood tracker (🙂 button in the reader toolbar)
6. A reading-buddy mascot that reacts to streaks, resuming, and finishing a book
7. Encouraging quote banner on the dashboard
8. Weekly themed reading challenge, rotated automatically by ISO week
9. Streak freeze — one motivational "protect my streak" token per week (client-side only; doesn't alter the server's real streak calculation)
10. Chapter self-check quiz — a quick reflection prompt at chapter ends, saved locally

**Easier:**
11. Font live-preview swatches in reader settings — see the change before applying
12. Smart resume — the "welcome back" toast now includes a short text snippet of exactly where you left off
13. Auto night-mode — reader theme switches automatically by time of day unless you've manually picked a theme this session
14. Labeled + color-coded bookmarks (color is a lightweight local accent on top of the existing label field)
15. Reading pace comparison — session summary now shows today's pace vs. your personal average
16. Personalized "reading journey" export — a downloadable Markdown file combining session stats, position, and highlights
17. "Getting started" onboarding checklist on the dashboard (set a goal, favorite a book, write a review, join a club) that auto-dismisses once complete
18. Adjustable session timer badge in the reader toolbar, plus a gentle screen-dimming wind-down cue when the break reminder fires
19. Quick-reaction bar (🔥📖❤️) on book pages, visible to everyone — backed by a new `BookReaction` table and `GET`/`POST /library/books/{id}/reactions` endpoints
20. Chapter-boundary triggers that alternate between trivia (#4) and the self-check quiz (#10) as you cross into a new chapter

All of the above are additive and namespaced per-user in `localStorage` (via `js/engage.js`), except the reaction bar, which is genuinely shared and required the one new backend table + two endpoints. Because that's a new table, `python migrate_db.py` needs to be re-run after pulling this build.

## Navigation simplification

The top nav (`renderNav()` in `js/api.js`, shared by every page) previously showed 5 links at the top level plus a single flat "More" dropdown holding 6 more — 11 destinations with little grouping. Simplified to:

- **Top-level** (3): Dashboard, Library, Community — the everyday destinations
- **My Reading** dropdown: Journal, My Progress, My Shelves — personal reading tools
- **More** dropdown: Reading Clubs, Mentors, Live Discussions, Reading Resources, Opportunities Hub — community/extra features

Admin still appears at the top level for Administrator/Moderator accounts only. No pages or routes changed — only how they're grouped and labeled in the nav.

## Reader bug-fix pass

A focused pass on the Online Reader (`reader.html`) to make its existing features behave correctly rather than add new ones:

1. **Click-to-read-aloud silently did nothing on the right-hand page** of a two-page spread. The character offset was computed after the page had already re-rendered, so it was measured against a fresh, unrelated set of DOM nodes and always came back empty. Fixed by computing the offset first, then switching pages.
2. **Double-tapping to bookmark also turned the page** (once per tap), because `touchend` never stopped the browser from firing its own synthetic `click` afterward, which triggered the page-nav-zone's `onclick` on top of the touch handling. `touchend` now prevents that default and drives navigation/bookmarking itself, so a double-tap only bookmarks and a single tap only turns the page.
3. **Most reader settings silently reset every time the book was reopened**: font family, margins, theme (including custom colors), read-aloud rate/voice, auto page-turn speed, highlight color, and annotation style (highlight vs. underline) were all applied for the session but never saved. They're now persisted the same way sound/goal/brightness/alignment already were, and restored on load — so a reader's setup sticks between visits instead of only lasting until the next reload.

## Database model upgrade

The schema (`app/models.py`) got a structural pass across all ~45 tables:

- **Referential integrity**: every `ForeignKey` now declares `ON DELETE CASCADE` or `SET NULL` explicitly, instead of relying on defaults. Deleting a book cleans up its reviews/favorites/progress; deleting a live session cleans up its chat, polls, RSVPs, etc. "Who did this" references (added_by, host_id, reviewed_by...) go `SET NULL` so the record survives. `database.py` now turns on `PRAGMA foreign_keys=ON` for every SQLite connection (off by default in SQLite, silently ignored otherwise) and `PRAGMA journal_mode=WAL` for better concurrent read/write behavior.
- **Duplicate prevention**: `UniqueConstraint`s on every join/membership/vote table (favorites, reading progress, club memberships, session RSVPs/mutes/bans/co-hosts, poll votes, message reactions, saved opportunities, notification preferences, etc.) so the same user can't double-join, double-vote, or double-favorite at the DB level, not just in application logic.
- **Data validity**: `CheckConstraint`s on rating fields (1–5), reading progress percentage (0–100), `users.role`, and the two backend-owned status machines (`content_reports.status`, `mentorship_requests.status`).
- **Query performance**: composite indexes for the access patterns the routers actually use — session chat ordered by time, notifications filtered by read state, reviews filtered by approval, reports by target, DMs by thread.
- **Freshness tracking**: `updated_at` (auto-set via `onupdate`) added to the tables that get edited after creation — users, books, reviews, discussion posts/replies, live sessions, content reports, mentorship requests.

Because these are structural constraints, not just new columns, SQLite needs the tables recreated — `python seed.py` alone isn't enough this time. Use the new migration script instead, which backs up any existing `readers_club.db` before rebuilding:

```bash
cd backend
python migrate_db.py    # backs up old DB (if any), rebuilds schema, reseeds demo data
```

## Setup

```bash
cd backend
pip install -r requirements.txt
python migrate_db.py    # creates SQLite DB on the upgraded schema + demo accounts/books
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** — the FastAPI app serves the frontend directly, no separate server needed.

## Demo logins (from seed.py)

| Role | Email | Password |
|---|---|---|
| Administrator | admin@readersclub.ng | admin123 |
| Moderator | mod@readersclub.ng | mod12345 |
| Mentor | mentor@readersclub.ng | mentor123 |
| Member | chidinma@example.com | member123 |
| Member | samuel@example.com | member123 |

These accounts come pre-attached to seeded demo content (reviews, discussions, a club, a mentorship, etc.) — useful for exploring the app populated.

**Simple test accounts** (no extra demo content attached — just the account, for testing role privileges cleanly):

| Role | Email | Password |
|---|---|---|
| Administrator | testadmin@readersclub.ng | Test1234 |
| Moderator | testmoderator@readersclub.ng | Test1234 |
| Mentor | testmentor@readersclub.ng | Test1234 |
| Member | testuser@readersclub.ng | Test1234 |

Role privileges are enforced server-side via three dependency guards in `auth.py`: `require_admin` (Administrator only — role changes, account removal, audit log), `require_staff` (Administrator + Moderator — book/content management, moderation, Book of the Month), and `require_mentor_or_admin` (Administrator + Mentor — Live Discussion sessions, Reading Resources, mentorship responses).

8 seeded books span African Literature, Entrepreneurship, Personal Development, Finance, Christian, History, and Technology categories, with full plain-text content for testing the online reader. A Book of the Month, a 7-Day Reading Challenge, a sample review, and a pinned welcome discussion are pre-loaded.

## Notes on scope

This build now covers all 22 SRS modules end-to-end, including Live Discussions, Campus Reading Clubs, Reading Mentorship, Reading Resources, and the Opportunities Hub. Live Discussions uses short-poll chat (client re-fetches every 3 seconds) rather than true WebSockets, keeping this a single-process FastAPI app with no extra real-time infrastructure — see Part 1/5 of the design docs for the WebSocket upgrade path if real-time push becomes a requirement at scale.

Known simplifications:
- Book "content" is stored as plain text (not EPUB/PDF parsing) for the in-browser reader.
- Cover images are solid-color placeholders (`cover_color`) rather than uploaded image files.
- Notifications are in-app only in this pass (no email delivery).
- Live session chat uses polling, not WebSockets (see above).

## Child safety, donations & branding (latest pass)

**Brand logo** — the club's logo now appears as the favicon and browser
tab icon on every page, in the navbar (landing page, auth pages, and the
shared in-app nav), and in the footer.

**Donations** — a "💛 Support the Club" link in the footer leads to
`donate.html`, showing the Opay bank-transfer details (Account Name:
Samuel Oluwasegun Godwin, Account Number: 8149008290). The app never
collects or processes card/payment data itself; donors transfer directly
via their own bank/Opay app. An optional, anonymous "thank-you note" form
lets supporters flag that they've sent a gift, visible to admins/mods
under Admin → Donations. The donation page explicitly asks parents/
guardians/supporters to give, not children.

**Real social links** — the footer's Facebook, Instagram, TikTok, YouTube,
and WhatsApp Community icons now point to the club's actual accounts.

**Avatars** — Admin, Moderator, and Mentor accounts can upload a real
profile photo (Profile page → Profile Picture; 3MB max, jpg/png/webp).
Members instead pick one of 8 illustrated preset avatars (4 male, 4
female) — no member is ever prompted to upload a photo of themselves.

**Guardian consent & age-aware registration** — signup now asks for an
age range. Anyone under 18 must also provide a parent/guardian's name,
email, and explicit consent before the account is created; everyone must
accept the new Privacy & Child Safety Policy. See `age_bracket`,
`guardian_name`, `guardian_email`, `guardian_consent` on the `User` model.

**Safety Center** (`safety.html`) — safeguarding info, Nigeria emergency
contacts (NAPTIP, Police 112), and a "Report a concern" form usable with
or without an account (`POST /api/reports/safety-concern` is public).

**Privacy & Child Safety Policy** (`privacy-policy.html`) — plain-language
policy covering what's collected, what isn't, and parent/guardian rights,
written with NDPR/NDPA principles in mind.

**Security hardening**
- New `SecurityHeadersMiddleware` adds CSP, X-Frame-Options: DENY,
  X-Content-Type-Options: nosniff, Referrer-Policy, and a Permissions-Policy
  that blocks camera/mic/geolocation/payment access app-wide.
- JWT access tokens now expire in 12 hours by default (was 7 days) —
  override with `RC_ACCESS_TOKEN_EXPIRE_MINUTES`. Shorter-lived tokens
  matter more here since members often share school/family devices.
- The frontend auto-logs out after 20 minutes of inactivity.

**Schema change** — this adds new columns/tables (`users.age_bracket` and
guardian fields, `donation_acknowledgments`, nullable `reporter_id`/
`content_id` on `content_reports`). Run `python migrate_db.py` from
`backend/` to rebuild and reseed the database, same as any other schema
upgrade in this project.
#   g w i n s _ r e a d e r s _ c l u b  
 