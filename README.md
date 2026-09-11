# ApplyPilot

ApplyPilot is a local FastAPI + Playwright assistant for preparing Workday job applications. It fills deterministic profile data, creates the five configured work records, asks an LLM for required unknown answers when configured, pauses for human intervention when needed, and stops at Review. It never clicks Submit.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp config/profile.example.yaml config/profile.yaml
cp .env.example .env  # optionally add LLM_API_KEY and LLM_MODEL
uvicorn app.main:app --reload
```

Open `http://localhost:8000`, paste a Workday job URL, and select Workday. Login, registration, MFA and CAPTCHA remain in the visible browser. The application accepts one active browser session at a time.

## Profile

`config/profile.yaml` is the only long-term data source. It contains personal/contact data, phone settings, one Ann Arbor education record, exactly five `work_experiences`, explicit voluntary disclosures, links and `saved_answers`. The resume path is uploaded but never parsed. Keep this file private; it is ignored by Git.

Before a browser opens, ApplyPilot rejects profiles that do not contain five complete work records. Existing Workday cards are checked for conflicts before missing cards are added.

## Answers and review

Answers resolve from profile facts, saved answers, then the configured OpenAI-compatible LLM. Required dropdown/radio answers must match an option visible on the page. LLM-generated or reused answers are marked in the local audit. API/provider failures and unsupported controls pause the session.

At Review, the browser remains open. The local audit shows the answer, source, reason and LLM context. The review approval endpoint can save approved answers to `profile.yaml`; it does not submit the application. Review the employer page and click Submit yourself.

## Tests

```bash
.venv/bin/pytest -q tests/unit/test_workday_v1.py
.venv/bin/pytest -q tests/integration/test_workday_records.py
```

The integration fixtures launch a local HTTP server and Chromium. A real Workday URL should only be used for an explicit manual end-to-end check; it may create a saved draft on the employer site.
