"""Infrastructure layer.

Implements application-layer ports against real technology (PostgreSQL/SQLAlchemy persistence
mapping, Redis event publishing, etc.): `infrastructure -> application, domain` (D2). Depends on
`app.application` and `app.domain`; never depended on by them.
"""
