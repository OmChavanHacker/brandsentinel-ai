<div align="center">

# BrandSentinel AI

### *Deterministic Pre-Publication Governance with Dual Control, Versioned Policy, and Signed Evidence*

![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)
![Next.js 14](https://img.shields.io/badge/Next.js-14-000000?logo=nextdotjs&logoColor=white)
![Ed25519](https://img.shields.io/badge/Signatures-Ed25519-8A2BE2)
[![CI](https://github.com/OmChavanHacker/brandsentinel-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/OmChavanHacker/brandsentinel-ai/actions)

**CodeNexus India 2026 | Grand Finale (Round 3) | Problem statement by Inkloom AI**

**Live demo:*[* _add the deployed URL here_](https://brandsentinel-ai-pjex.vercel.app) | Final technical report:[** _add the PDF link here_](https://drive.google.com/file/d/1iol73537dw1Jn1QRRwsKgPOHbR5RjITI/view?usp=sharing)

</div>

---

## Why BrandSentinel AI?

Content is published by employees, agencies and AI tools, and nobody sees every draft first. In our Round 1 survey of 18 practitioners, 17 used generative AI to draft content, 14 verified drafts against official guidelines only rarely or inconsistently, and outdated facts were the most reported error (8 of 18).

BrandSentinel AI checks a draft **before** it is published and follows one rule: **cite or stay silent.**

- A finding is asserted only when a rule or a dated fact supports it, and it shows its source.
- A claim with no approved source goes to a person. It is never labelled a violation.
- Retrieval uses a local `all-MiniLM-L6-v2` model. **No external LLM or hosted AI service is called at run time.**
- Approval is tied to the exact text that was reviewed (SHA-256), so edits invalidate earlier sign-offs.

### The three lanes

| Lane | Name | Meaning | What the reviewer sees |
|---|---|---|---|
| **A** | Grounded violations | A rule or dated fact applies | Highlighted words, rule ID and section, source passage, expiry date, rewrite with diff preview. Nothing is applied automatically |
| **B** | Unverified claims | No approved source supports the claim | The sentence, the reason, the nearest rule and its score, routed to human review. Never labelled a violation |
| **C** | Advisory tone | Tone and style observations | Kept separate from rule findings; informational for the reviewer |

---

## The three Round 3 capabilities

### 1. Signed evidence pack and offline verifier

`POST /api/report/export` | `verify_report.py` | `POST /api/report/verify`

- ReportLab builds a deterministic PDF (`invariant=1`) with a canonical `manifest.json` embedded as an attachment.
- A detached **Ed25519** signature (`report.sig.json`) covers the SHA-256 of the final PDF bytes and the manifest hash. The public key is `backend/keys/report_signing.pub.pem`.
- The manifest holds the content hash, policy version, findings with citations, every decision (user, role, time), the ledger entries, and the chain-check result at export time.
- The app can verify a pack in the browser and offers a **tampered copy** download that fails verification.

### 2. Dynamic policy ingestion and impact diff

`POST /api/policy/upload` | `GET /api/policy/versions/{id}` | `GET /api/policy/versions/{id}/impact` | `POST /api/policy/versions/{id}/activate`

- Upload CSV, JSON or Markdown rulebooks. The validator reports **every** problem with its line number (HTTP 422): duplicate IDs, non-ISO dates, unknown risk classes, NUL bytes, size limits.
- Valid files are staged in the background (terms compiled, passages embedded) and become an immutable `PolicySnapshot`. Activation swaps a single reference, so a review in flight keeps the policy it started with.
- The **impact diff** runs a 35-draft reference set against the active and the staged snapshot. On our benchmark, recall moved from **60% to 90%** after the sample policy update.

### 3. Dual-control separation of duties

`POST /api/auth/login` | `POST /api/action` | `GET /api/session/{id}`

- **Argon2id** password hashing and **HS256 JWT** role binding. The server reads identity and role from the token and ignores any role in a request body.
- A review that triggers a `financial` or `health` rule routes to the **`PENDING_DUAL`** state. Approval needs one `MARKETING_HEAD` **and** one `LEGAL_COUNSEL`, and they must be different people. The same person trying both slots gets **HTTP 403**.
- Approvals are bound to `content_sha256`. A one-byte edit invalidates earlier sign-offs.
- Every state change carries a `version`. A stale request returns **409 `STALE_STATE`**. An `Idempotency-Key` makes retries return the original result.

---

## Seeded demo accounts

**Demo accounts, synthetic data.** The credentials are public on purpose so evaluators can act as every role.

| Username | Password | Role | Purpose |
|---|---|---|---|
| `maya.creator` | `demo-maya` | `CREATOR` | Default signed-in user. Writes and submits drafts |
| `rahul.brand` | `demo-rahul` | `BRAND_LEAD` | Policy upload and activation |
| `marcus.marketing` | `demo-marcus` | `MARKETING_HEAD` | High-risk approval slot 1 |
| `priya.legal` | `demo-priya` | `LEGAL_COUNSEL` | High-risk approval slot 2 |
| `sam.dual` | `demo-sam` | `MARKETING_HEAD` + `LEGAL_COUNSEL` | Deliberate dual-role trap: proves one person cannot fill both slots |

---

## 3-minute judge walkthrough

The same eight steps appear in the in-app tour panel, where each box ticks itself as you complete the action.

| # | Do this | You should see | Time |
|---|---|---|---|
| 1 | Load the financial-guarantee scenario and press **Run governance check** | Findings in Lanes A, B and C with measured timings | 0:00 |
| 2 | In Lane A, preview and apply the rewrite | Strikethrough and green diff; nothing changes until you confirm | 0:30 |
| 3 | **Send for approval** | Banner: high-risk claim, two distinct sign-offs required (`PENDING_DUAL`) | 0:50 |
| 4 | Sign in as `sam.dual`, approve as Marketing Head, then try Legal as the same user | **403**: one person cannot fill both slots | 1:10 |
| 5 | Edit one character of the draft | The existing sign-off shows as invalidated; re-run the check | 1:40 |
| 6 | Approve as `marcus.marketing`, then `priya.legal` | State moves to `APPROVED` only after both distinct approvers sign | 2:00 |
| 7 | Export the signed report, verify it in the app, then download the tampered pack and verify it again | First verification passes; the tampered copy fails | 2:20 |
| 8 | Open the policy page. Upload `sample_rulebook_bad.csv`, then `sample_rulebook_good.csv`, review the impact diff and activate | Line-by-line 422 errors, then a before-and-after comparison and a new policy version | 2:40 |

---

## Local quickstart (fresh clone)

**Requirements:** Python 3.11, Node.js 18+, Git. The first start downloads the ~90 MB embedding model once.

### Backend

```bash
git clone https://github.com/OmChavanHacker/brandsentinel-ai.git
cd brandsentinel-ai/backend

python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .\.venv\Scripts\python.exe is used below instead
pip install -r requirements.txt

export AUTH_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export LEDGER_HMAC_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export REPORT_SIGNING_KEY_B64="$(python -c 'import base64, os; print(base64.b64encode(os.urandom(32)).decode())')"
export ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

<details>
<summary><b>Windows PowerShell version</b></summary>

```powershell
cd brandsentinel-ai\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$env:AUTH_JWT_SECRET = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
$env:LEDGER_HMAC_KEY = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
$env:REPORT_SIGNING_KEY_B64 = & .\.venv\Scripts\python.exe -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
$env:ALLOWED_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"

.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

</details>

| Variable | Purpose |
|---|---|
| `AUTH_JWT_SECRET` | Signs HS256 login tokens |
| `REPORT_SIGNING_KEY_B64` | Base64 32-byte Ed25519 private key seed for report signing. **Environment only, never committed** |
| `LEDGER_HMAC_KEY` | Key for the HMAC-SHA256 audit ledger. Without it a development key is used and a warning is logged |
| `ALLOWED_ORIGINS` | Comma-separated browser origins allowed by CORS |

Check `http://127.0.0.1:8000/api/health`. `retrieval_mode` should read `embedding`; `lexical_fallback` means the model could not load and a simpler word-overlap matcher is in use (the UI labels this too).

### Frontend

```bash
cd ../frontend
npm install
echo "NEXT_PUBLIC_API_URL=http://127.0.0.1:8000" > .env.local     # PowerShell: Set-Content .env.local "NEXT_PUBLIC_API_URL=http://127.0.0.1:8000" -Encoding ascii
npm run dev
```

Open `http://localhost:3000`. You are signed in as Maya. For a production build: `npm run build && npm start`.

### Tests

```bash
cd backend
pytest
```

GitHub Actions runs the tests and the Next.js production build on every push.

### Verify a report offline

```bash
python backend/verify_report.py report.pdf report.sig.json --pubkey backend/keys/report_signing.pub.pem
```

Prints `PASS` or `FAIL` for four checks and exits with code 1 if any fail. Flip one byte in either file and run it again to see it fail.

> **Local runs and the public key.** The committed `backend/keys/report_signing.pub.pem` matches the key used by our deployed demo. Reports you generate locally are signed with **your** `REPORT_SIGNING_KEY_B64`, so they verify only against the matching public key. To produce it:
>
> ```bash
> python -c "import base64,os;from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey as K;from cryptography.hazmat.primitives.serialization import Encoding as E,PublicFormat as F;print(K.from_private_bytes(base64.b64decode(os.environ['REPORT_SIGNING_KEY_B64'])).public_key().public_bytes(E.PEM,F.SubjectPublicKeyInfo).decode())" > local_pub.pem
> ```
>
> On PowerShell, pipe the output through `Set-Content local_pub.pem -Encoding ascii` instead of using `>`. Do not commit `local_pub.pem` over the project key.

---

## API reference

| Endpoint | Purpose |
|---|---|
| `POST /api/auth/login` | Argon2id login; returns an HS256 JWT carrying user and role |
| `GET /api/session/{id}` | Restore workspace, last review and approvals after a refresh |
| `POST /api/review` | Run the governance check; store the content hash; derive routing |
| `POST /api/action` | Send for approval or approve, with role, content-hash and version checks |
| `POST /api/policy/upload` | Validate and stage a CSV, JSON or Markdown rulebook |
| `GET /api/policy/versions/{id}` | Staging status: indexing, ready or failed |
| `GET /api/policy/versions/{id}/impact` | Before-and-after impact diff against the reference set |
| `POST /api/policy/versions/{id}/activate` | Make a staged version the active policy |
| `POST /api/report/export` | Build and sign the evidence pack |
| `POST /api/report/verify` | Verify a pack in the app |

Errors return typed JSON: `401` unauthenticated, `403` role not allowed or same person, `409` `STALE_STATE` or draft changed after review, `422` validation (with line numbers for uploads).

---

## Architecture

```
 Browser: Next.js 14 (TypeScript, Tailwind)
   persona bar | tour | three lanes | diff preview | approvals | policy page | verifier
                              |
                              v
 FastAPI API layer
   Argon2id login + HS256 JWT (role from token, never from the body)
   version / expected_version + Idempotency-Key | typed errors | masked 500s | CORS
        |                         |                        |
        v                         v                        v
 Session store             Policy store             Review engine
  workflow, version,        immutable                claim isolation, rules,
  approvals,                PolicySnapshot,          dated facts, local
  content_sha256,           atomic pointer swap,     all-MiniLM-L6-v2
  HMAC-SHA256 ledger        background staging       retrieval -> Lanes A, B, C
        |
        v
 Evidence service (ReportLab PDF + manifest.json + Ed25519 signature)
        - - - - - - - - - -> verify_report.py (offline, no access to our system)
```

### Key management

- The Ed25519 **private key lives only in the `REPORT_SIGNING_KEY_B64` environment variable.** It is never committed.
- The **public key is committed** at `backend/keys/report_signing.pub.pem`, and its key ID is printed in the signature file.
- The offline verifier checks: the Ed25519 signature, the PDF bytes against the signed hash, the embedded manifest against the signed hash, and that each ledger block links to the hash of the one before it.
- **Scope:** the verifier cannot recompute the ledger's HMAC digests, because that needs the server's secret. The signature attests that our server verified the full chain at export time.

### What is protected

| Threat | Control |
|---|---|
| Approving text the approver never saw | SHA-256 content binding; edits invalidate sign-offs |
| Spoofing a role from the browser | Role comes from a signed JWT, not the request body |
| One person filling both approval slots | Distinct user IDs enforced on the server (403) |
| Editing the audit ledger | Keyed HMAC-SHA256 hash chain; verification reports the first broken block |
| Altering an exported report | Ed25519 signature over the PDF bytes and the manifest |
| Lost updates and double submits | Optimistic `version` check and `Idempotency-Key` replay |
| Malformed or hostile uploads | Size limits, NUL-byte and encoding checks, schema validation |
| Draft text leaving our system | Local embeddings; no hosted AI service at run time |

---

## Measured results

Measured by the team during Round 3 testing. A free-tier host is slower on its first request after idle time.

| Measure | Result | Round 2 target |
|---|---|---|
| Validate and index 200 rules | 1.8 s | Under 30 s |
| Build and sign a report | about 140 ms | Under 3 s |
| Recall on the 35-draft benchmark, old to new policy | 60% to 90% | Reported with misses |

The benchmark is a set of 35 short drafts written by the team and labelled with the rule IDs they should trigger. It shows direction, not a statistical estimate, and false-positive edge cases are documented with it in the repository.

---

## Honest limitations

- **Ephemeral persistence.** Uploaded policies are written to the host's disk. On free-tier hosting a container restart resets the policy to the built-in `v1.0-base`.
- **State is in memory.** Sessions, accounts and audit ledgers reset on restart. A session expires after an hour of inactivity.
- **Single-step policy activation.** The planned second approval before activation and a rollback flow were not built.
- **Synthetic, team-authored benchmark.** Detection quality on real rulebooks and real marketing copy is not measured.
- **Verifier scope.** It does not recompute HMAC digests (see Key management).
- **Ledger limit.** Deleting the newest entries cannot be detected from inside the chain, and someone holding the HMAC key could rewrite it.
- **Bulk tamper test not run.** The Round 2 target of 50 or more altered report packs was not run at that scale. Single-change tampering is rejected and shown live in the walkthrough.
- **Demo accounts are public.** Anyone can act as any role. This is intentional for evaluation. There is no SSO, multi-factor authentication or key rotation.
- **Text only, English only.** Images, slides and documents are not analysed.
- **Not built in this round:** guideline-clarity analytics, comments and revision history, a Brand Reviewer stage, an agency workspace, a manager dashboard, and dismissing a finding with a reason.

### Roadmap

| Horizon | Work |
|---|---|
| Next 30 days | Durable storage (PostgreSQL for accounts, ledgers and policy versions; object storage for reports); activation approval and rollback |
| Next 90 days | Key management with rotation (KMS or HSM); ledger head anchored outside the process; single sign-on and a multi-tenant model |
| Later | Image and slide checks, guideline-clarity analytics, comments and revision history, CMS and design-tool plugins, on-premise deployment |

---

## Team and disclosure

| Member | Role |
|---|---|
| **Om Ramdas Chavan** | Team Lead. Architecture, review engine and policy snapshots, impact diff and benchmark, Next.js interface, signed-report layout, privacy and access-control design |
| **Abhinav Dipak Kadam** | Backend and workflow engineer. Authentication, `PENDING_DUAL` state machine, concurrency and idempotency, policy validator and staging, Ed25519 signing and verifier, audit ledger, tests and CI |

**CodeNexus India 2026, Inkloom AI problem statement.**

- **AI assistance:** an AI assistant (Claude by Anthropic) helped us draft documents, review our code for security and reliability issues, and write parts of the backend, frontend, tests and report generator. We reviewed, ran and take responsibility for everything submitted.
- **Models and data:** the only model is `all-MiniLM-L6-v2` (sentence-transformers), used locally for retrieval. All policies, drafts, benchmark items and accounts are synthetic. The Round 1 survey (18 respondents) is our own primary research.
- **Libraries:** Next.js, React, TypeScript, Tailwind CSS, FastAPI, Pydantic, argon2-cffi, PyJWT, cryptography, ReportLab, pypdf, sentence-transformers, pytest and GitHub Actions, each under its own licence.
