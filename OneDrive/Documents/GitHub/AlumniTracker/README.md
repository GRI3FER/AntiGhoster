# AlumniTracker

AlumniTracker is a Flask/SQLite foundation for alumni networks with verified email access and mandatory per-network alumni review.

## Rules implemented

- Students must use a verified email whose domain ends in `.edu`.
- Alumni may use personal email, but must verify it and receive manager approval for every network.
- Alumni approval is required for open, password-protected, and application-based networks.
- Pending alumni can retrieve their application and limited-preview state, but cannot retrieve the member directory.
- Changing from student to alumni moves active memberships to `pending`.
- Managers can approve, reject, or request additional evidence.

## Run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:ALUMNI_TRACKER_SESSION_SECRET = "replace-me"
$env:ALUMNI_TRACKER_VERIFICATION_SECRET = "replace-me"
python app.py
```

`POST /api/register` returns a verification token only when Flask testing/development mode is enabled. Production deployments must deliver that token through an email provider rather than exposing it in the response.

## Core API

- `POST /api/register`, `POST /api/verify-email`, `POST /api/login`
- `POST /api/networks`
- `POST /api/networks/<id>/join`
- `GET /api/networks/<id>/application`
- `GET /api/networks/<id>/members`
- `POST /api/networks/<id>/members/<user_id>/review`
- `POST /api/me/role`
