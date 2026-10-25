# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- CodeQL analysis for Python and GitHub Actions on pushes and pull requests to `main` and on a weekly schedule.
- Dependabot version updates for pip, Docker and GitHub Actions, with minor and patch updates grouped per ecosystem.
- README screenshots: a GraphQL session against the seeded demo and the schema reference.
- Roadmap items tracked as GitHub issues under the v0.2.0 milestone.

### Changed

- CI workflow runs with a read-only `GITHUB_TOKEN`.
- Test count in the README updated to 47.

## [0.1.0] - 2026-10-25

First public release of Agri Field Monitor.

### Added

- Farmers, fields (boundary as GPS points, area via shoelace on a local projection, reported in m², hectare, acre, bigha and decimal), seasons with AWD windows
- Field tubes (pipes) with manual and device readings; irrigation events; field visits with notes, GPS and photos
- AWD rules: `IRRIGATION_DUE` when the daily minimum level stays at or below the field threshold (default -15 cm) for N consecutive days since the last irrigation, `OVERFLOW` for wasted standing water, `SENSOR_SILENT` when readings stop; one open alert per field and kind enforced by a DB constraint, auto-resolved when the condition clears
- Weekly progress report grouped by field, union or upazila: readings, average and minimum level, field-days below threshold, irrigation events per field, visits, alerts, and an estimated water saving against continuous flooding
- Strawberry GraphQL API with filtered, paginated queries and validated mutations; GraphiQL at `/graphql/`
- DRF endpoints for the things GraphQL is bad at: multipart photo upload (type and size validated) and token issuance; `/health/`
- Stateless JWT (PyJWT) shared by a Django middleware (GraphQL) and a DRF authentication class (REST)
- Django admin for every model with filters, search, inlines and a bulk "resolve" action
- `seed_demo` with Rajshahi and Bogura upazilas (Paba, Godagari, Tanore, Sherpur, Shibganj, Dhunat), three weeks of readings and one field in each alert state; `awd_check` command for cron
- Postgres via `DATABASE_URL`, SQLite for local work and tests; Dockerfile (gunicorn, non-root) and compose with a scheduler container

[Unreleased]: https://github.com/AkibUllah/agri-field-monitor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AkibUllah/agri-field-monitor/releases/tag/v0.1.0
