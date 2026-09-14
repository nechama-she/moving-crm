# Customer move intake and verified public page

## Status and rollout

The implementation is local; no migration, deployment, SMS, email, or SmartMoving backfill has been run. The new records use the existing `leads`, `lead_jobs`, and `lead_attachments` tables. `backend/migrate.py` adds portal access/session/upload/rate-limit records, a separate `walkthrough_requests` table, optional job stop types, nullable lead/job company assignment, and nullable upload staff attribution for customer uploads.

Deploy only after the feature migration and configuration have been reviewed. The separate production SmartMoving timestamp migration is not part of this feature. Intake leaves SmartMoving IDs, quote number, and SmartMoving created time empty; it never calls SmartMoving. Public-intake LiveSwitch conversations use the customer name when there is no quote number and use the assigned company's phone.

## Configuration

Set these in the existing backend SSM prefix (or environment):

- `PUBLIC_MOVE_API_KEY`: a new random server-to-server secret, stored as SecureString. Keep it out of browser code.
- `PUBLIC_MOVE_EMAIL_FROM`: an SES-verified sender address. SES must be enabled for the recipients/environment in use.
- SMS verification uses the existing Aircall credentials and the lead company's Aircall number (or its phone matched to an Aircall number). When the lead has no company, it uses the company checked as **Default company** in the Companies directory. Only one company can be selected; selecting another clears the previous default. This does not assign or change the lead/job company. No default is selected automatically. An assigned company with no usable sender produces an error, not a fallback to another company. `PUBLIC_MOVE_SMS_ENABLED` and SNS setup are no longer used for verification texts.
- Existing `JWT_SECRET`, `ATTACHMENTS_BUCKET`, database and LiveSwitch settings remain required.

CloudFormation automatically sets the API Lambda's `PUBLIC_MOVE_ORIGIN` to the deployed frontend: the CloudFront HTTPS address in dev, or the configured custom domain in production (CloudFront when no custom domain is configured). No manual SSM origin parameter is needed. An existing `PUBLIC_MOVE_ORIGIN` SSM parameter still overrides this default; remove it if the deployment-managed address should be used. URL construction never trusts the request Host header. Apply the CloudFormation stack update to activate this configuration; a code-only Lambda update is not sufficient.

To test, call `POST /api/inventory` in Swagger and open the returned `url` in a browser. The frontend's `/move/:accessId` route is a standalone customer page, outside CRM login and navigation. Customer phone/email verification still applies; use contact details you control when testing.

CloudFormation parameter `PublicMoveEmbedOrigins` accepts space-separated HTTPS website origins allowed to embed the page. With its empty default, the `frame-ancestors` response header allows same-origin embedding only. The frontend document remains on the CRM origin when embedded; it calls the API from that origin, so the parent site does not need unrestricted API CORS access.

Email verification requires SES send-email permission; verification texts use Aircall, with no SNS fallback. Confirm actual delivery with designated test recipients before release. Verification SMS content and Aircall response bodies are redacted from application logs. No codes are printed or returned by the API.

## Intake API

`POST /api/inventory`

Headers:

- `Content-Type: application/json`
- `x-api-secret: <PUBLIC_MOVE_API_KEY>`
- `Idempotency-Key: <unique submission ID, 8�128 characters>`

Example body:

```json
{
  "first_name": "Jane",
  "last_name": "Smith",
  "source": "Website",
  "move_date": "2026-10-23",
  "pickup": "123 Main Street, Baltimore, MD 21201",
  "delivery": "456 Oak Street, Miami, FL 33101",
  "stops": [
    {"address": "789 Pine Street, Richmond, VA 23220", "type": "pickup"},
    {"address": "100 Elm Street, Raleigh, NC 27601"}
  ],
  "phone": "+12405550123",
  "email": "jane@example.com"
}
```

`company_id` is optional. Phone or email is required; both may be supplied. A stop type may be `pickup`, `delivery`, or omitted. Pickup/delivery themselves are addresses, and stops are preserved in order.

Response:

```json
{
  "lead_id": "<existing-leads-table ID>",
  "job_id": "<existing-jobs-table ID>",
  "url": "https://crm.example.com/move/<access-id>#key=<private-link-token>"
}
```

Retrying the same key and body returns the same records/link. Reusing the key with different data returns 409. The returned URL is private; keep it out of third-party analytics. Its secret is in a fragment, not a server request URL.

Embed the complete returned URL in an iframe on an approved origin, with `referrerpolicy="no-referrer"`, a descriptive title, and enough height (approximately 1200px initially). The customer can also open the URL as a standalone page. Do not sandbox without allowing scripts and same-origin access, or API calls will not function normally.

## Customer verification and access

Before verification, the page exposes only masked available contact methods. Codes go only to the phone/email stored on the lead, never a contact supplied to the verification endpoint. Codes expire after 10 minutes, allow five attempts, and are single-use. Resends require 60 seconds and are limited to five per hour per access record. API request rates are persisted in the database.

A verified session lasts eight hours, is held only in page memory, and is scoped to one public access record. Reloading the page requires verification again. Changing phone/email invalidates existing sessions and challenges. Links expire after 90 days and staff can revoke access. Customer APIs check the link and verified session independently. Tokens are hashed; OTPs use a server-keyed hash. Public responses are no-store and no-referrer. The public page exposes no host link, staff notes, assignment controls, draft price, or other leads.

This implements selected OWASP token/session/upload protections. It is not a formal ASVS certification or independent penetration test. Uploads are private, limited by count/bytes, and checked for allowed file signatures; this is not a malware-scanning service. The customer UI uploads directly to a short-lived private S3 staging destination, then the server validates size and file signature before copying it into job files. This avoids API Gateway/Lambda request-body size limits. Abandoned staging files expire through bucket lifecycle.

## Staff workflow

- **Live Calls** shows requests and an **unassigned** filter for intake leads without a company. Open a lead or its customer-page controls to connect a company.
- Customer-page controls appear on the lead and inside the LiveSwitch panel. Set cubic feet and price, save a draft, then **Publish estimate**. The public page shows the last published snapshot; later drafts remain private until published again.
- The customer page refreshes details every 15 seconds, including published estimates and scheduled appointments.
- Customers request a time in their own words and timezone. Staff assign a rep, enter a scheduled time (the staff browser's local time is converted to UTC), and set Requested/Scheduled/Completed/Cancelled. Only one active request per job is allowed.
- Pickup and delivery remain the ends of the route. **Stop types (optional)** on the job edits the saved intermediate-stop types. Save changed stop addresses before editing types.
- Customer uploads go into that job's existing files. If a LiveSwitch conversation already exists, the API queues their transfer. Otherwise, staff connect a company and use **Sync customer files to LiveSwitch**; conversation setup also happens in the worker. The HTTP request returns `202` after enqueueing, without copying files. Staff controls poll sync status every four seconds without replacing unsaved estimate drafts. Work continues after the page closes.
- A dedicated SQS-triggered Lambda processes one file per job, with a 180-second timeout, and commits each successful file immediately. Queue redelivery skips completed files; saved upload destinations are reused if the transfer outcome was interrupted. An expired/rejected destination is not automatically replaced because the original transfer may already have succeeded; staff must check LiveSwitch before resetting that destination. Failed files and their error messages are shown in customer-page controls.
- Deploy the new `public_move_uploads` sync columns, `PublicMoveSyncQueue`, worker, and dead-letter mapping together. The template supplies `PUBLIC_MOVE_SYNC_QUEUE_URL`; the existing API package also includes `public_move_sync_handler.py`. The deployment pipeline refreshes the worker code on each deployment. Repeated invocation failures/hard timeouts are sent to the dead-letter handler, which marks affected files failed instead of leaving the UI permanently syncing. No migration or cloud deployment has been executed locally for this change.

## Verification performed

Tests use an isolated SQLite database and mocked message delivery. They cover public authorization, wrong/expired/revoked links, OTP reuse/expiry/attempt limits, contact changes, cross-job session rejection, contact validation, typed stops, duplicate meeting prevention, and published-estimate isolation. Existing LiveSwitch and model-mapping tests also run. Live SES/SNS delivery, external iframe domains, production PostgreSQL migrations, and production upload sizing require a configured deployment test.
