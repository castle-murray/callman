# CallManager — Django Backend

Django REST API backend for CallManager, a labor and event staffing management platform. Companies create events with call times, define labor requirements, request workers via SMS, and track clock-in/out with time entries and meal breaks.

This backend serves both a legacy Django template app (`/app/`) and a modern React SPA frontend.

## Tech Stack

- **Django 5.2** with Django REST Framework 3.16
- **Django Channels** + Daphne (ASGI) for WebSocket support
- **PostgreSQL** database
- **Redis** for Channel layers
- **Twilio** for SMS notifications
- **Stripe** for payments
- **Tailwind CSS** (legacy template app)

## Prerequisites

- Python 3.10+
- PostgreSQL
- Redis (for WebSocket support)
- Twilio account (for SMS)
- Stripe account (for payments)

## Getting Started

```bash
# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy .env and configure
cp .env.example .env

# Run migrations
python manage.py migrate

# Start the development server
python manage.py runserver
```

For WebSocket support, use Daphne instead:

```bash
python run_daphne.py
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | Set to `True` for development |
| `ALLOWED_HOSTS` | Comma-separated list of allowed hostnames |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated list of trusted origins |
| `DB_ENGINE` | Database engine (e.g. `django.db.backends.postgresql`) |
| `DB_HOST` | Database host |
| `DB_PORT` | Database port |
| `DB_NAME` | Database name |
| `DB_USER` | Database user |
| `DB_PASS` | Database password |
| `FRONTEND_URL` | React frontend URL (default: `http://localhost:5173`) |
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Twilio phone number for sending SMS |
| `STRIPE_SECRET_KEY` | Stripe secret key |
| `STRIPE_PUBLISHABLE_KEY` | Stripe publishable key |

## Project Structure

```
callman/
├── callman/              # Project config (settings, urls, asgi, wsgi)
├── callManager/          # Main app — models, template views, consumers
│   ├── models.py         # All data models (36 models)
│   ├── consumers.py      # WebSocket consumers
│   ├── views.py          # Template-based views
│   └── view_files/       # Modular template view files
├── api/                  # REST API app
│   ├── urls.py           # ~90 API endpoints
│   ├── views.py          # Auth views (login, logout, user_info)
│   ├── serializers.py    # DRF serializers
│   ├── utils.py          # Helpers (frontend_url for SMS links)
│   └── view_files/       # Modular API views
│       ├── event_views.py
│       ├── call_times.py
│       ├── request_views.py
│       ├── time_tracking.py
│       ├── worker_views.py
│       ├── user_views.py
│       ├── owner_dashboard.py
│       ├── notifications.py
│       └── sms_views.py
├── theme/                # Tailwind CSS (legacy template app)
├── manage.py
├── requirements.txt
└── run_daphne.py         # Daphne ASGI server launcher
```

## Data Model

```
Company → Event → CallTime → LaborRequirement → LaborRequest → TimeEntry → MealBreak
```

### User Roles

| Role | Access |
|------|--------|
| **Administrator** | System-wide access |
| **Owner** | Company admin, billing (Stripe) |
| **Manager** | Full company access — events, workers, settings |
| **Steward** | Assigned events only |
| **Worker** | Self-service — availability responses, clock-in/out |

Roles are implemented as OneToOneField relations on User, checked via `hasattr(user, 'manager')` etc.

## Authentication

- **API**: DRF Token Authentication — `POST /login/` returns a token, sent as `Authorization: Token <key>`
- **Template app**: Django session auth at `/app/login/`

## WebSocket Endpoints

| Path | Description |
|------|-------------|
| `/ws/notifications/` | Real-time notifications for managers |
| `/ws/labor-requests/<slug>/` | Live labor request status updates |

Requires Redis running on `localhost:6379`.

## API Endpoints

All API views are function-based with `@api_view` / `@permission_classes` decorators.

### Auth & Users
- `POST /login/` — Login, returns auth token
- `POST /logout/` — Logout
- `GET /user/info/` — Current user info and role
- `GET /user/profile/` — User profile with pending requests
- `POST /forgot-password/` — Send password reset email
- `POST /reset-password/<token>/` — Reset password

### Events
- `GET /events/list/` — List company events
- `GET|PATCH|DELETE /event/<slug>/` — Event details
- `POST /create-event/` — Create event
- `POST /event/<slug>/send-messages/` — Send SMS to workers
- `POST /event/<slug>/assign-steward/` — Assign steward

### Call Times
- `POST /call-time/<slug>/add-call-time/` — Add call time to event
- `PATCH /call-times/<slug>/edit/` — Edit call time
- `DELETE /call-times/<slug>/delete/` — Delete call time
- `GET /call-times/<slug>/tracking/` — Time tracking data

### Labor & Requests
- `POST /call-times/<slug>/add-labor/` — Add labor requirement
- `GET /request/<slug>/fill-list/` — Workers to fill a request
- `POST /request/<slug>/worker/` — Request a specific worker
- `POST /request/<slug>/send-messages/` — Send request SMS

### Workers
- `GET /workers/` — List company workers
- `GET /workers/<slug>/history/` — Worker event history

### Notifications
- `GET /notifications/` — List notifications
- `POST /notifications/<id>/read/` — Mark as read
- `POST /notifications/clear-all/` — Clear all
