# Option Risk Platform

- Before working, read `PROJECT_BRIEF.txt`; it records the design agreed with the user.
- Repository: https://github.com/limbj/option-risk-platform.git
- Local project root: `D:\git\option-risk-platform`.
- The preparation conversation prepared handoff documents only. Application implementation belongs in the user's new project conversation, not in the preparation conversation.
- Use Django + Django REST Framework + Django ORM/migrations for the backend. Keep the financial calculation and ML packages independent of Django.
- In the new project conversation, pursue the entire MVP through Stages 1-7 in the brief. Stage 1 is the starting point, not the stopping point. After implementing and validating a stage, continue to the next stage without requiring routine stage-by-stage approval.
- Keep a concise progress record of completed work, verification results, unresolved issues, and the next action. If execution is interrupted, use this record and the actual repository state to resume. Ask only when required information, permissions, or a material scope decision cannot be resolved from the user's instructions; do not claim unverified stages are complete.
- Record material design changes and their rationale instead of silently expanding the scope. Finishing the seven-stage MVP does not authorize unrelated later extensions or external deployment.
- Preserve immutable input/model snapshots and explicit calculation provenance. Never replace failed prices or incomplete portfolio totals with zero.
- Validate finite numbers, dates, currencies, quantity signs, contract multipliers, and volatility/rate units at the relevant boundaries.
- Test numerical correctness separately from API, persistence, worker recovery, and ML approximation quality.
- Use Linux containers for Celery development on Windows. Keep test databases, generated datasets, model artifacts, and secrets out of Git.
- The preparation conversation did not authorize an initial commit or push for this repository. Follow the user's instructions in the new conversation for implementation and Git operations.
- Communicate with the user in Korean.

## Implementation conversation decisions (2026-11-08)

- The user authorized intermediate commits and pushes after validated milestones.
- Stage 7 ends with local Docker execution, a reproducible demo, CI, and documentation.
  Do not deploy to an external server or publish the app on the internet.
- The default local demo opens without a login screen, using an existing demo session internally.
  Preserve session/CSRF and ownership checks. Explicit multi-user authentication remains available;
  automatic demo entry must be rejected by production settings.
