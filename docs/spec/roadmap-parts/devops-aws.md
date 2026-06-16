# Roadmap — DevOps / AWS

> My slice of the production roadmap for the Bizz_up rebuild. Cost-aware, solo-friendly (Omer + Claude, steady pace).
> Grounded in: `spec/architecture.md`, `spec/data-model.md`, `system-map/infrastructure.md` (§6 "AWS Production"),
> `decisions/0001/0002/0005/0006`, `bugs.md`, `security-issues.md`.
> **Scope note:** I provision and wire the *platform* (compute, network, secrets, data services, CI/CD, observability).
> I do **not** build app features — auth/RLS, the bot engine, the gateway code belong to the backend/gateway agents.
> Where a decision was explicitly handed to "the `devops_aws` agent" I make it here and mark it **DECISION**.

---

## Decisions I own (handed to me by the specs)

These were left open for this phase. My calls, with rationale:

- **DECISION-1 — Crown-jewel KEK = AWS KMS, not app-held.** (data-model open Q1, decision 0005.) The `whatsapp_credentials.auth_state`
  DEK is wrapped by a **KMS Customer-Managed Key (CMK)**; the KEK never leaves KMS, never lands in `.env` or the DB.
  Envelope encryption: app calls `kms:GenerateDataKey` / `kms:Decrypt`; a DB dump is useless without KMS + IAM. The **PII data
  key and the HMAC key** are *separate* secrets in Secrets Manager (they can be app-held material), but the WhatsApp KEK is KMS.
  Rationale: it's the single most dangerous secret (account takeover), KMS gives hardware-backed keys + per-call CloudTrail audit
  for ~$1/mo/key, and it cleanly satisfies "never in the DB, separate from the PII key."
- **DECISION-2 — Managed Redis = ElastiCache for Redis (single node, cluster-mode disabled) for MVP.** (decision 0006: "the
  `devops_aws` agent will provision it.") Private subnet only, `transit_encryption_enabled` (TLS) + AUTH token, `at_rest_encryption`.
  One `cache.t4g.micro` node is plenty for last-10-messages-per-active-chat; no Multi-AZ replica at MVP (cost). Reserve a replica/
  Multi-AZ flip for Phase 2+ scale.
- **DECISION-3 — Stable public endpoint = ALB + ACM + Route53.** Kills ngrok and fixes **B15** (rotating URL) and removes the
  per-session Meta re-registration pain. ALB chosen over API Gateway: we have long-lived/streaming needs (the dashboard streams
  the live QR over an authed channel — data-model table 4) and a persistent gateway service; ALB path-routing to two target groups
  is cheaper and simpler than API-GW for this shape.
- **DECISION-4 — Compute = ECS on Fargate** (not EKS, not EC2). Solo-friendly: no node/k8s management, scale-to-task, pay-per-use.
  Two services with **different scaling profiles** (see Phase 1, the gateway-statefulness task).
- **DECISION-5 — Postgres stays on Supabase for MVP; revisit RDS at scale.** The data lives there already (infra §6: "the one
  externalized piece"). I do **not** migrate the DB in Phase 1 — out of scope and risky. I *do* lock down the network path
  (connect over TLS, app uses the **non-service role** per data-model, service key retired). RDS Postgres is a Phase 2+ option if
  we outgrow Supabase or want everything in one VPC/IAM boundary. Marked **needs verification** with Omer on cost/lock-in.

---

## Phase 0 — Foundations (before any app code ships to AWS)

The goal: an AWS account that is safe to spend money in and safe to put secrets in, plus the build pipes. Small, do-once tasks.

### 0.1 — AWS account baseline & guardrails
- **What:** One AWS account (or Org + a single `prod` account). Root locked down (MFA, no access keys), an admin IAM user/SSO for
  Omer, region pinned (suggest `eu-central-1` Frankfurt or `eu-west-1` Ireland — EU for Israeli-privacy data-residency comfort;
  marked **needs verification**), CloudTrail on, IAM password/key policy.
- **Why:** Everything else assumes a sane account. Region choice touches the launch **compliance** item (Israeli privacy law /
  data protection — keep PII in an EU region with a clear residency story).
- **Depends-on:** —
- **Effort:** S
- **Risk:** Picking the wrong region = painful to move later (Supabase project region should match). Decide region *first*.

### 0.2 — Budget alarm on DAY ONE
- **What:** AWS Budgets monthly cost budget + CloudWatch billing alarm → SNS → Omer's email (oyc3333@gmail.com). Thresholds at
  50/80/100% of a small cap (e.g. $50–100/mo to start).
- **Why:** Explicitly required "day one." Solo project: a runaway Fargate task, NAT gateway, or a Gemini-quota-driven loop can
  quietly burn money. This is the cheapest insurance there is.
- **Depends-on:** 0.1
- **Effort:** S
- **Risk:** None real. Set the email subscription confirmation early (SNS needs a click).

### 0.3 — Networking (VPC) skeleton
- **What:** One VPC, 2 AZs, public subnets (ALB) + private subnets (Fargate tasks, ElastiCache). Security groups: ALB→tasks on app
  ports only; tasks→Redis on 6379; tasks→internet (Gemini, Supabase, Google OAuth) egress. **Cost note:** a NAT Gateway is ~$32/mo
  + data — for MVP consider a single NAT, or VPC endpoints / a public-subnet task with locked SG to avoid NAT entirely. Marked
  **needs verification** (NAT vs endpoints cost tradeoff).
- **Why:** Redis "private network only" (data-model: Redis has no RLS, must never be internet-exposed), and Fargate tasks need a
  home. This is the boundary that makes "Cache runs on a private network only" true.
- **Depends-on:** 0.1
- **Effort:** M
- **Risk:** NAT Gateway is the silent cost driver in small AWS setups — size egress deliberately. Over-locked SGs = debugging pain.

### 0.4 — Secrets Manager + KMS keys provisioned
- **What:** Create the **KMS CMK** for the WhatsApp KEK (DECISION-1). Create Secrets Manager entries (names only, values rotated):
  DB connection (non-service role), Redis AUTH token, **PII data key**, **HMAC key** (for `customer_phone_hash`), session secret,
  Google OAuth client/secret, Gemini API key. **Rotate every value carried over from the old `.env`** — per security C1 they are
  all compromised.
- **Why:** Fixes **C1** (plaintext `.env`) and **M3** (`change-me` session default). The app "fails to start if a secret is
  missing" (data-model) — so the secret *names* must exist before app deploy. The KEK must exist before the gateway can encrypt.
- **Depends-on:** 0.1
- **Effort:** M
- **Risk:** **Rotating `ENCRYPTION_KEY` requires re-encrypting existing rows** (security C1/M2). For the clean rebuild there's no
  legacy data to migrate, so this is a non-issue *if* we start fresh — confirm we are not carrying old encrypted leads forward.

### 0.5 — ECR repositories
- **What:** Two private ECR repos: `bizzup-backend`, `bizzup-gateway`. Lifecycle policy to expire untagged images (cost).
- **Why:** Fargate pulls images from ECR. Prereq for any container deploy.
- **Depends-on:** 0.1
- **Effort:** S
- **Risk:** None. Just remember the lifecycle policy or image storage creeps.

### 0.6 — CI/CD pipeline (build → push → deploy)
- **What:** GitHub Actions (assuming GitHub; **needs verification**): on push to `main`, build both Docker images, push to ECR,
  update the ECS services. OIDC role from GitHub→AWS (no long-lived AWS keys in CI). A **secret-scanning / "no secret in image"**
  CI gate, and the data-model's required CI test: **fail the build if `auth_state` / the KEK ever appears in a response or log.**
- **Why:** Solo dev needs repeatable, one-command deploys — replaces the machine-specific `.bat`/`.ps1` (B14) and dev-server
  launches (B25). The secret-leak gate enforces the data-model's "CI test fails the build" rule.
- **Depends-on:** 0.5
- **Effort:** M
- **Risk:** OIDC trust policy is fiddly to get right first time. Keep the first pipeline dumb (build+push+force-new-deployment).

---

## Phase 1 — MVP platform (gets leads + handoff + bot-builder + try-me live)

This is the bulk of my work: containerize the two services, run them on Fargate behind HTTPS, give the gateway durable encrypted
session storage, stand up Redis, wire logs/alarms. The MVP can't go live without a stable webhook URL and persistent gateway state.

### 1.1 — Containerize backend (FastAPI)
- **What:** Production Dockerfile for the FastAPI backend: pinned deps (fixes **B2** unpinned/`pip install` per-run), multi-stage
  build, `gunicorn`/`uvicorn` workers **without `--reload`** (fixes **B25**), non-root user, healthcheck endpoint. Config via
  env/Secrets, not files (fixes hardcoded `localhost`/paths B14).
- **Why:** Fargate runs containers. Pinning + no-reload + healthcheck are the prod-readiness fixes the infra scan called out.
- **Depends-on:** 0.5; backend agent's app being deployable (app code is theirs, the image is mine)
- **Effort:** M
- **Risk:** The old deps are heavy (`sentence-transformers`, `crawl4ai`) — but those are RAG (Phase 3). MVP image should **exclude**
  RAG deps to stay small/fast. Coordinate with backend agent on the MVP dependency set.

### 1.2 — Containerize Baileys gateway (Node) + the statefulness design  ⭐ hardest task
- **What:** Production Dockerfile for the Node/Baileys gateway (`vite build` the admin UI if kept, or drop it; no dev server).
  **The hard part:** Baileys is **one stateful WebSocket socket per business session** — it does **not** scale horizontally like a
  stateless web app (infra §6 "Biggest blocker"). Design: run the gateway as a **single-replica Fargate service** (desired=1, no
  autoscaling) so there is exactly **one writer** per session. Session creds (`auth_state`) are read/written to the
  **`whatsapp_credentials` DB table, envelope-encrypted via KMS** (NOT local disk — fixes **M1**), so a task replacement re-hydrates
  sessions from the DB instead of forcing every business to re-scan a QR.
- **Why:** This is the make-or-break of the whole product on AWS. Get single-writer wrong → duplicate sockets → WhatsApp bans
  (decision 0001 ban risk). Get persistence wrong → every deploy logs out every customer's business. Encrypting at rest fixes the
  crown-jewel exposure (M1, data-model table 5).
- **Depends-on:** 0.4 (KMS key), 1.1 pattern; gateway agent's DB-backed auth-state code
- **Effort:** L
- **Risk:** **Highest in the whole roadmap.** Single-replica = a brief outage on every deploy/crash (acceptable at MVP; mitigate
  with fast health-check restart). Horizontal scale later needs session-sharding (one session→one task) — **reserve this as a
  Phase 2+ design**, do not solve it now. Also: the inbound receive path was **never tested end-to-end** (decision 0001, B1) — the
  platform must support the **one real end-to-end receive test** that's a Phase-1 exit criterion.

### 1.3 — ALB + ACM HTTPS + Route53 (the stable endpoint)
- **What:** Public ALB, ACM cert (DNS-validated) for the app domain, Route53 hosted zone + records. Path/host routing:
  dashboard+API → backend target group; the gateway's webhook/`/send` reachable by the backend (internal path) and the gateway
  admin/QR over the authed channel. HTTP→HTTPS redirect; TLS 1.2+; HSTS.
- **Why:** **Kills ngrok, fixes B15** (rotating URL) and **B3** (webhook URL no longer ephemeral). A stable HTTPS URL means the
  webhook is registered **once**. HTTPS is also a hard requirement for the **compliance** items (Privacy Policy / data protection
  expect TLS; Google OAuth requires HTTPS redirect URIs in prod).
- **Depends-on:** 0.1, 0.3; a registered domain (**needs verification** — does Omer own one?)
- **Effort:** M
- **Risk:** ACM DNS validation + Route53 delegation can stall if the domain is registered elsewhere. Buy/point the domain early.

### 1.4 — ECS services + task definitions (run it all)
- **What:** ECS cluster; two Fargate services — **backend** (autoscale 1→N on CPU, stateless) and **gateway** (fixed desired=1,
  per 1.2). Task defs inject secrets via Secrets Manager ARNs + the KMS-grant for the gateway role. Right-sized CPU/mem
  (start 0.25 vCPU / 0.5GB each). Rolling deploys with circuit breaker (auto-rollback on failed health check).
- **Why:** This is the actual "make it run" step. The split scaling profile (stateless backend vs single-writer gateway) is the
  core of DECISION-4 and directly enforces the no-duplicate-socket rule.
- **Depends-on:** 1.1, 1.2, 1.3, 0.4, 0.6
- **Effort:** M
- **Risk:** Mixing the two scaling models in one cluster is fine, but autoscaling the *gateway* by accident would be catastrophic
  (duplicate sessions). Lock the gateway service to desired=1 and document why loudly.

### 1.5 — ElastiCache for Redis (live chat)
- **What:** Provision ElastiCache Redis per **DECISION-2**: single `t4g.micro`, private subnet group, TLS + AUTH token (from
  Secrets Manager), at-rest encryption, SG allowing only the Fargate tasks. Backend connects with `rediss://`.
- **Why:** Decision 0006 makes Redis **required in prod** for live chat (last ~10 msgs + bot/human/closed status, 60-min TTL) and
  for handoff continuity across instances. Fixes the old volatile in-RAM state (**B11**) and the multi-instance OAuth-state problem
  (**B12** — pending OAuth state can also move to Redis with TTL).
- **Depends-on:** 0.3, 0.4
- **Effort:** S
- **Risk:** "Redis has no RLS" (data-model) — isolation is the **app's** job (business_id in every key). My job is *only* network +
  auth + TLS + encryption; I must make sure it's **never** in a public subnet. Don't undersize so far it evicts hot chats.

### 1.6 — CloudWatch logs + alarms
- **What:** Both services log to CloudWatch (structured JSON, log retention set to control cost). Alarms: service unhealthy /
  task crash-looping, gateway disconnected (WhatsApp session down = revenue-impacting), ALB 5xx rate, Redis evictions/CPU, ECS
  CPU/mem. SNS → Omer's email. A **log-scrubbing guard**: per security L1/data-model, **secrets and raw PII must never appear in
  logs** — enforce a structured logger and a CI/log check.
- **Why:** Solo operator has no on-call team; alarms are how Omer learns the gateway dropped before a customer complains. The
  no-secrets-in-logs rule is a stated security requirement (L1, M2 "fail loud but don't log the secret").
- **Depends-on:** 1.4, 1.5
- **Effort:** M
- **Risk:** Alarm fatigue / log cost if retention is infinite. Set sane retention (e.g. 30d) and only page-worthy alarms to email.

### 1.7 — Secrets wiring & startup fail-closed (verification pass)
- **What:** Confirm every service reads secrets from Secrets Manager/KMS at boot and **fails to start if any is missing** (no
  `change-me` fallback — fixes **M3**). Confirm the app uses the **non-service Postgres role** (service key retired — the root of
  C2-class cross-tenant leaks). Confirm gateway role has the KMS grant and the dashboard role does **not** (data-model:
  "dashboard/API role has no grant — not even SELECT" on `whatsapp_credentials`).
- **Why:** Ties the platform to the security model. The least-privilege role split (gateway-role vs dashboard-role) is enforced
  partly at the DB (grants/RLS — backend agent) and partly by **which IAM/KMS grants each Fargate task gets** (mine).
- **Depends-on:** 0.4, 1.4
- **Effort:** S
- **Risk:** A wrong IAM/KMS grant that lets the dashboard task decrypt `auth_state` would silently break the crown-jewel isolation.
  Verify with a deny-test.

### 1.8 — Gateway webhook durability & rate-limit posture (platform support)
- **What:** Platform-side support for two gateway bugs the gateway agent fixes in code: persist the registered webhook URL so it
  survives restarts (**B3**) — now trivial since the URL is the stable ALB domain; and provide the infra hook for a retry/
  dead-letter on inbound webhook delivery (**B21**) — at MVP a simple in-task retry is fine; reserve SQS DLQ for Phase 2+.
- **Why:** A dropped inbound message = a lost lead. The stable endpoint (1.3) already removes the *main* cause of webhook breakage.
- **Depends-on:** 1.3, 1.4
- **Effort:** S
- **Risk:** Low at MVP. Full durable queueing is deliberately deferred (don't over-build for one business going live).

---

## Phase 2+ — Post-MVP (back-office, booking, RAG, scale)

### 2.1 — Back-office: platform-metrics data path  (BACK-OFFICE — my part)
- **What:** The back-office is **FULL** scope (manage businesses/users, billing VIEW, support+impersonate, platform metrics). My
  slice = the **platform-metrics** plumbing: a CloudWatch dashboard for ops health (tasks, Redis, ALB, gateway-up-per-business) and
  the data path that lets the back-office app surface **cross-tenant** product metrics (active businesses, sessions connected,
  leads/day). This likely needs a **read path that intentionally crosses tenants** — so it runs under a dedicated, audited
  back-office role, never the normal tenant-scoped app role.
- **Why:** Operating a multi-tenant SaaS solo means "is every business's WhatsApp still connected?" must be answerable at a glance;
  the gateway-disconnected alarm (1.6) feeds this.
- **Depends-on:** 1.6; back-office app (other agents)
- **Effort:** M
- **Risk:** A cross-tenant metrics role is a privilege-escalation footgun — must be read-only, audited (CloudTrail), and separate
  from the tenant app role.

### 2.2 — Back-office: support impersonation — audit infrastructure  (BACK-OFFICE — my part)
- **What:** Support "impersonate a business" is a feature other agents build; **my** part is the audit/observability backbone:
  every impersonation action emits an immutable audit log (CloudWatch Logs / dedicated store) with who-impersonated-whom-when.
- **Why:** Impersonation touches another tenant's PII (leads). For **Israeli privacy law / data-protection compliance**, accessing
  customer PII under impersonation must be logged and reviewable. This is a compliance-adjacent infra requirement.
- **Depends-on:** 2.1
- **Effort:** S
- **Risk:** If impersonation isn't audited from day one of the back-office, you can't prove who saw what — a compliance gap.

### 2.3 — Compliance hosting: accessibility + Terms/Privacy + data-protection (LAUNCH COMPLIANCE — my part)
- **What:** Platform-side enablers for the required launch-compliance items: (a) **HTTPS/TLS everywhere + HSTS** (done in 1.3) so
  the privacy/data-protection story holds; (b) host the **Terms of Service + Privacy Policy** pages (static, served by the frontend
  CDN — see 2.6); (c) a **data-retention / deletion capability** — infra to honor "delete a customer's data" (leads are encrypted +
  in Postgres; Redis auto-expires; backups must also respect deletion). The **accessibility (נגישות / WCAG)** work is front-end, but
  I ensure nothing in the hosting layer (e.g. a broken CDN cache or a redirect loop) undermines it.
- **Why:** Launch compliance is **REQUIRED** (Israeli privacy law, WCAG, Terms+Privacy). Data-protection law implies a right to
  deletion and data-residency — both have an infra dimension (where data lives = region choice 0.1; how it's deleted = backups).
- **Depends-on:** 0.1 (region), 1.3 (HTTPS), 2.6 (CDN for static legal pages)
- **Effort:** M
- **Risk:** Backups are the sneaky compliance gap — if a deleted lead still sits in a 30-day DB snapshot, the deletion promise is
  false. Define backup-retention + deletion handling explicitly. Data residency must match the region chosen in 0.1.

### 2.4 — Booking support (Phase 2 feature) — infra is largely already there
- **What:** Booking (decision 0004 Phase 2, fixes B7) is mostly app + DB work; infra impact is minor (same backend service, the
  `book/{slug}` public path through the existing ALB). My only adds: ensure the public booking path has **rate-limiting / WAF**
  (it's an unauthenticated write path — security M4) and that booking PII gets the same encryption treatment (M5) — the encryption
  *keys* are already provisioned (0.4).
- **Why:** Booking opens a public, unauthenticated write endpoint; that needs abuse protection at the edge.
- **Depends-on:** 1.3, 1.4; booking feature (other agents)
- **Effort:** S
- **Risk:** Unauthenticated public write = spam/abuse target. Add AWS WAF rate-based rules before booking goes live.

### 2.5 — RAG infrastructure (Phase 3)
- **What:** RAG (decision 0004 Phase 3) needs: pgvector (already in Supabase), Supabase Storage (or S3) for uploaded source files,
  and — critically — the **heavy ML deps** (`sentence-transformers` embedding model, `crawl4ai`). These bloat the backend image and
  embedding is CPU-heavy. Design: either a **separate RAG worker service/image** (so the chat backend stays lean), or move
  embeddings to a managed embedding API. Plus an async ingestion path (SQS + worker) so document upload doesn't block requests.
- **Why:** Keeping RAG's heavy footprint out of the MVP/chat image (noted in 1.1) is what keeps the live bot fast and cheap; when
  RAG lands it needs its own compute story.
- **Depends-on:** 1.1, 1.4
- **Effort:** L
- **Risk:** The embedding model cold-start + memory can blow up Fargate task size/cost. Strongly consider a managed embedding API
  vs self-hosting `sentence-transformers`. Decide before committing.

### 2.6 — Frontend hosting (S3 + CloudFront)
- **What:** The rebuild's React+Tailwind frontend (`spec/architecture.md` part 1) is **static** → host on **S3 + CloudFront**
  (OAC, HTTPS via ACM, SPA routing). This also hosts the static **Terms/Privacy** pages (2.3).
- **Why:** Cheaper, faster, and more scalable than serving HTML from FastAPI (the old model). Decouples frontend deploys from the
  backend. CDN + caching also supports the accessibility/perf side of compliance.
- **Depends-on:** 0.1, 1.3 (shared ACM/Route53); frontend build (other agents)
- **Effort:** M
- **Risk:** SPA routing + OAuth redirect URIs need correct CloudFront/Route53 config; CORS between the CDN origin and the API must
  be set deliberately (the old system had no CORS by design — that changes once frontend is a separate origin).

### 2.7 — Horizontal scale & HA (when one business becomes many)
- **What:** When load grows: Multi-AZ for Redis (flip DECISION-2), backend autoscaling tuned, and — the hard one — **gateway
  session sharding** (route each business's session to a specific task, e.g. consistent hashing / a session-router, so we can run
  >1 gateway task without duplicate sockets). Possibly migrate Postgres to **RDS** (DECISION-5) for one VPC/IAM boundary.
- **Why:** The single-replica gateway (1.2) is the scaling ceiling. This is the planned escape hatch — explicitly **deferred** so
  MVP ships.
- **Depends-on:** 1.2, 1.4, 1.5
- **Effort:** L
- **Risk:** Gateway sharding is genuinely hard (stateful sticky routing). Don't attempt until real load demands it; premature = the
  #1 way to slip the MVP.

### 2.8 — Infrastructure as Code (Terraform or CDK)
- **What:** Codify everything above (VPC, ECS, ALB, ECR, ElastiCache, Secrets/KMS, Route53, alarms, budgets) in **IaC**.
  Recommendation: **Terraform** (portable, huge ecosystem) — or **CDK** if we want to stay all-TypeScript/Python with the app.
  Marked **DECISION pending Omer's preference**.
- **Why:** Reproducibility, review-able infra changes, disaster recovery, and it documents the platform. The roadmap brief
  sequences this as "**then** IaC" — i.e. after the click-built MVP proves the shape, codify it.
- **Depends-on:** Phase 0 + Phase 1 done (codify what exists)
- **Effort:** L
- **Risk:** Importing already-created (click-built) resources into IaC state is tedious and error-prone. Either commit to IaC-first
  for a resource, or budget time for clean import. Doing IaC *too* early (before the shape is proven) wastes solo time — hence it's
  Phase 2+.

---

## SUMMARY

**Phases**
- **Phase 0 — Foundations:** safe AWS account → account baseline + region, **Budget alarm day-one**, VPC/network, Secrets Manager
  + **KMS KEK**, ECR, CI/CD. Small do-once tasks; nothing app-specific.
- **Phase 1 — MVP platform:** containerize backend + gateway, **ALB+ACM+Route53 (kills ngrok / fixes B15)**, ECS/Fargate (stateless
  backend + **single-writer stateful gateway**), **ElastiCache Redis** for live chat, CloudWatch logs/alarms, secrets fail-closed +
  least-privilege role split. This is what makes leads+handoff+bot-builder+try-me actually run in prod.
- **Phase 2+ — Post-MVP:** back-office metrics + impersonation-audit infra, **compliance hosting** (HTTPS/HSTS, Terms/Privacy
  pages, data-retention/deletion + residency), booking edge-protection, RAG compute, S3+CloudFront frontend, horizontal-scale +
  gateway sharding, and finally **IaC (Terraform/CDK)**.

**The 5–8 biggest tasks**
1. **Containerize the Baileys gateway with DB-backed, KMS-encrypted session storage + single-writer Fargate service** (1.2) — the
   hardest task and the product's make-or-break; fixes M1, supports the unverified receive path (decision 0001/B1). **(L)**
2. **ALB + ACM + Route53 stable HTTPS endpoint** (1.3) — kills ngrok, fixes B15/B3, unblocks Google OAuth + compliance TLS. **(M)**
3. **ECS/Fargate services with split scaling profiles** (1.4) — stateless backend autoscales; gateway locked to desired=1 to avoid
   duplicate WhatsApp sockets (ban risk). **(M)**
4. **Secrets Manager + KMS for the crown-jewel KEK** (0.4, DECISION-1) — rotate all compromised `.env` secrets (C1), fail-closed
   startup (M3), KMS-wrapped DEK for `auth_state`. **(M)**
5. **ElastiCache Redis for live chat** (1.5, DECISION-2) — required by decision 0006; private+TLS+AUTH; fixes B11/B12. **(S)**
6. **CI/CD with secret-leak gate** (0.6) — repeatable deploys replacing the machine-specific scripts (B14/B25) + the data-model's
   "fail the build if the KEK/auth_state leaks" test. **(M)**
7. **Compliance hosting: data-retention/deletion + residency + HTTPS** (2.3) — required launch compliance (Israeli privacy law,
   Terms/Privacy, WCAG-supporting CDN); the backups-vs-deletion gap is the subtle part. **(M)**
8. **IaC (Terraform/CDK)** (2.8) — codify the proven platform last, for reproducibility + DR. **(L)**

**TOP RISK**
The **Baileys gateway statefulness** (task 1.2 / DECISION-4). Baileys is one stateful WebSocket socket per business and **cannot
scale horizontally like a normal web service** (infra §6 calls it "the biggest blocker"). Two failure modes, both severe: run more
than one task → **duplicate sockets → WhatsApp account bans** (Baileys is already unofficial/against ToS, decision 0001); or lose
the session creds on a task restart → **every business is logged out and must re-scan a QR**. The mitigation — single-replica
Fargate service (one writer) + KMS-encrypted `auth_state` persisted in Postgres so tasks re-hydrate — accepts a brief outage on each
deploy and **caps us at one gateway task until Phase 2+ session-sharding (2.7) is built.** Compounding it: the inbound **receive path
was never tested end-to-end** (decision 0001/B1), so the platform must enable that one real end-to-end test as a Phase-1 exit gate
before declaring the MVP live.

**Cross-references:** kills ngrok / B15, B3 (1.3); B11/B12 (1.5); B2/B25 (1.1, 1.2, 0.6); B14 (0.6); M1 (1.2); C1/M3 (0.4, 1.7);
M4/M5 (2.4); L1 no-secrets-in-logs (1.6). DB stays on Supabase for MVP (DECISION-5) — not migrated. **Needs verification with Omer:**
region/data-residency (0.1), domain ownership (1.3), NAT-vs-VPC-endpoints cost (0.3), GitHub as the CI source (0.6), Terraform-vs-CDK
(2.8), and whether any old encrypted data is carried forward (0.4).
