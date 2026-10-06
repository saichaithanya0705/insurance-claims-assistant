# Claim search, presentation and SQLite login update

Implemented October 6, 2026. This extends the completed [UI review fixes](UI_UX_FIXES_2026-10-06.md).

## What I did

| Change | Result |
|---|---|
| Search field | Replaced the exact-ID form and Open button with an anchored autocomplete. Partial IDs, existing headings/titles and incident words produce selectable claims while typing. Empty focus shows recent saved cases. |
| Keyboard and focus | Manual selection with Arrow Up/Down and Enter; Escape, Tab, blur and outside pointer clicks dismiss the popup. DOM focus stays on the input while `aria-activedescendant` identifies the highlighted result. |
| Request handling | 220 ms debounce; cancel superseded requests and ignore stale responses. Loading, unavailable, empty and malformed responses are explicit. IME composition and ordinary cursor editing remain intact. |
| Semantic recall | Added optional local MiniLM embeddings via FastEmbed/ONNX. Exact/prefix ID and literal title/text matches rank first; supplemental results say **Related meaning**. Queries and case descriptions are processed locally. |
| Presentation | Removed the global notice shown in the supplied image, provider/agent pills, Synapt sidebar/footer/browser branding and provider labels from the case screens. Business consequences and synthetic-evidence caveats remain readable. |
| Activity | Administrator Activity includes original findings, source metadata and paginated audit events: prompts, validated outputs, failures, stages and review decisions when recorded. User Activity contains workflow progress and validation without technical request logs. |
| Login and accounts | One login page supports server-derived user/admin roles. A localhost-only first-run setup creates the first admin; admin Accounts creates additional user or admin credentials. No default password is embedded in the app. |
| Server RBAC | Users submit/read/search their own claims. Admins read all cases, review briefs, manage accounts and access model/evaluation/connection tools. Direct IDs, library search and semantic suggestions share ownership enforcement. Existing unowned records remain admin-only. |
| SQLite and Git | Added a persistent local account database, password hashes, revocable sessions, account audit and claim ownership migration. Included `data/bootstrap/claims.sqlite` (28 saved investigations and their workflow/audit state, 5,685,248 bytes) and credential-free `auth.sqlite` (36,864 bytes) for Git. First default startup copies the case snapshot once, preserving existing working databases. |
| Packaging and documentation | Added the optional `search` dependency group and locked dependencies, explicit model/template/snapshot setup scripts, account schema, runtime ignores, updated setup instructions and rebuilt production UI assets. Initialized Git because this directory had no Git metadata. Added consistent text line endings and binary attributes for databases/screenshots, and removed incidental source whitespace for a clean Git check; Markdown hard line breaks remain valid. |

## What was the issue / root cause

The header treated reopening a saved claim as an exact identifier submission, despite the backend already supporting partial IDs and incident text. There was no suggestion state, popup, keyboard selection or stale-request control. Global infrastructure health was mixed with case-facing content, and the application had a shared optional API key without authenticated identities, claim owners or roles.

## Why this approach

The editable combobox with manual selection fits a search where several existing claims may match, and opening a claim requires an explicit choice. The implementation follows the [W3C combobox pattern](https://www.w3.org/WAI/ARIA/apg/patterns/combobox/) and its [list autocomplete example](https://www.w3.org/WAI/ARIA/apg/patterns/combobox/examples/combobox-autocomplete-list/). A result row contains the heading, full ID, case metadata and match type, making similarly named cases distinguishable.

For semantic search, the [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) describes its sentence embeddings; [FastEmbed documentation](https://qdrant.github.io/fastembed/Getting%20Started/) provides local ONNX inference. Runtime loads cached files only. The separate preparation script downloads the public model once into this project's D: drive artifacts directory. Embeddings are validated for count, shape, finite values and nonzero norm before ranking. Cached vectors refresh when a saved title/description changes. Missing/corrupt inference falls back to literal matches and reports semantic unavailability.

Accounts use salted scrypt hashes (`N=131072, r=8, p=1`), random server-side session tokens stored as hashes, 12-hour expiry, HttpOnly/SameSite cookies, CSRF tokens and origin checks on writes, generic login failures and failed-login throttling. These choices follow [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) and [CSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html) guidance. Roles and ownership are enforced by the API, including requests made outside the visible UI. Password validation errors omit submitted values.

The portable SQLite backup includes WAL changes consistently and is integrity-checked. The export script checks configured credentials before success. Passwords, account hashes, active sessions, local configuration and model caches remain in ignored working files; the committed authentication database contains only schema.

## Why not the alternative

- Keeping an Open button would preserve the extra action and would not address discovery while typing.
- A native datalist cannot reliably show rich claim metadata and gives limited control over asynchronous results and dismissal. A dialog would interrupt ordinary searching with unnecessary focus trapping.
- Automatically opening the first result on blur would risk opening the wrong claim, particularly with approximate matches. Blur dismisses only.
- Calling synonym expansion or TF-IDF “semantic search” would overstate the behavior. A real embedding model provides supplemental semantic recall here.
- Hosted embeddings or a new vector database would add external case-data transfer and operational dependencies for a small local catalog. Local inference with the existing SQLite catalog keeps setup bounded.
- Hiding admin navigation alone would leave endpoints exposed. The shared API key cannot establish an individual owner or role and cannot bypass the new login.
- Versioning the live account/session database would copy machine-specific authentication state. The committed schema and saved-case snapshot make a fresh checkout usable without exporting credentials.

## Why this works best here

Search remains fast and deterministic for IDs and familiar wording, with clearly marked approximate recall when useful. Source selection and review remain explicit. The case database is preserved, legacy cases need no body rewrite, and migrated ownership survives review updates. User-facing uncertainty remains visible while technical diagnostics are available to authorized administrators in each claim's Activity.

## Other valid patterns

| Pattern | Trade-off |
|---|---|
| Accessible combobox library | Useful for a broader widget suite; adds a dependency. This project currently needs one bounded search component. |
| SQLite FTS plus a vector index | Better for a large saved-case catalog; requires index lifecycle and pagination design. Current implementation scans the small metadata catalog and caches embeddings in memory. |
| Enterprise identity / OIDC | Appropriate for organization accounts, MFA and recovery; requires an identity provider and deployment configuration. |
| Managed relational database | Better for multi-host deployment and tenant administration; increases setup and operations beyond this local SQLite task. |

## Validation

| Check | Evidence |
|---|---|
| Backend suite | **98 passed**, including authentication, CSRF/origin checks, API-key bypass rejection, account persistence, session expiry/revocation, login throttle, role restrictions, direct-ID ownership, audit access, title/ID matching, malformed embeddings and database bootstrap preservation. |
| Frontend suite | **12 passed**, including combobox semantics, absence of Open, suggestion schema rejection and administrator-only technical Activity. |
| Production build | TypeScript and Vite passed; the compiled app is served at port 8000. |
| Static checks | Changed Python files pass Ruff; frontend lint has no errors and the same 14 pre-existing export/effect warnings. |
| Browser | Verified existing fixture user/admin login, logout, reload persistence, title and partial-ID suggestions, semantic recall, pointer selection, arrow/Enter selection, Escape/Tab/outside dismissal, no-match state, role navigation and detailed Activity log. |
| Responsive | Desktop plus 390×844 and 320×740 viewports; no horizontal overflow. Mobile popup height is limited to leave room for surrounding controls. |
| Real local embeddings | “vehicle struck from behind” finds the saved rear-end claim without literal overlap; unrelated spaceship/nonsense queries produce no matches. Initial model load/index check was about 1 second; warm small-catalog queries were about 4 ms on this machine. These are development observations, not a load benchmark. |
| Snapshot | SQLite integrity check passed, 28 saved investigations retained, configured credentials absent, auth template has zero account/session rows. |

Screenshots: [desktop autocomplete](search-rbac-2026-10-06/autocomplete-desktop.jpg), [admin accounts](search-rbac-2026-10-06/admin-accounts.jpg), [admin Activity](search-rbac-2026-10-06/admin-activity.jpg), [local first-admin setup](search-rbac-2026-10-06/login-setup.jpg). Mobile interaction and overflow were checked earlier in the browser; a later capture had desktop dimensions and was removed. The final browser revisit encountered a URL-policy block on the failed-navigation tab, so no replacement mobile screenshot is claimed.

## Use and limits

Open http://127.0.0.1:8000 and choose the first administrator credentials. Open **Accounts** to create user/admin accounts. Old cases are admin-only; new cases belong to the account that submitted them. The first-run setup form remains available for the user to complete.

Semantic matches are approximate and not a probability or claim decision. The 0.34 cosine cutoff was checked on this small saved-case collection; it is configurable and is not a domain-calibrated accuracy guarantee. This is English local search over saved investigations, not an expansion of the historical comparison dataset. Password reset, MFA, enterprise identity, organization tenancy, multiple application workers and real-device/screen-reader testing are outside this local implementation. Investigation submissions remain synchronous as documented in the earlier UI report.

The separate fixture server and test tabs were used only for synthetic validation and are cleaned up after verification. The main localhost application stays running for first-admin setup. GitHub publication is the user's requested next step.
