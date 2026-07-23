# Architecture

## Apps

| App | Responsibility |
|---|---|
| `accounts` | Custom `User`, `Role` (capability flags), RBAC permission classes |
| `compliance` | `Framework`, `ControlCategory`, `Control`, `ControlMapping`, seed + tree commands |
| `documents` | `Folder`, `FolderPermission`, `Document`, `DocumentVersion`, `FormTemplate` |
| `calendar_app` | `CalendarEvent` + merged review/audit/task feed |
| `notifications` | SES/SMTP email service, review-reminder engine, Celery task |
| `audit` | `AuditLog` + write-action middleware |

## Data model (essentials)

```
Framework 1─* ControlCategory 1─* Control *─* ControlMapping
                                     │
User(Role) ─owns→ Control / Folder / Document
                                     │
Folder (self-parent tree) 1─* Document 1─* DocumentVersion
   │                               └─ owner, review_cadence, next_review_date
   └─ FolderPermission (role|user → view/edit/manage, inherited)

CalendarEvent → optional Document / Control / owner
AuditLog → optional User
```

## RBAC resolution

`Folder.effective_access(user)` returns the highest of:

1. `manage` if superuser or `role.can_manage_folders`
2. `view` if `role.can_view_all`
3. `manage` if the user owns the folder
4. the highest `FolderPermission` for the user or their role, on this folder
   **or any ancestor** (inheritance)

Auditor roles are then capped at `view`. Documents inherit their folder's access;
a document owner may always edit their own document.

## Review-alert flow

```
Document.last_reviewed + cadence ─▶ next_review_date
        │
   daily scan (Celery beat OR cron: send_review_reminders)
        │
   for each lead in REVIEW_ALERT_LEAD_DAYS (30,14,7,1) not yet sent:
        └▶ email_service.send_review_reminder()
              ├─ EMAIL_PROVIDER=ses  → SESClient (boto3)
              └─ EMAIL_PROVIDER=smtp → Django SMTP backend
        │
   record lead in Document.reminders_sent  (dedupe)
   overdue documents get one distinct overdue notice
```

## Request/response auth

JWT (`/api/auth/token/`) issued to the React SPA; the axios client attaches the
access token and silently refreshes on 401. Session auth is also enabled so the
Django admin and browsable API work.
