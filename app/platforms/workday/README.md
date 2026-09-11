# Workday runner

The runner handles the five Workday wizard headings: My Information, My Experience, Application Questions, Voluntary Disclosures, and Review. It uses Workday `data-automation-id` controls, protects source-search Enter behavior, creates exactly the five profile work records, and never advances from Review.

Unknown required controls are inspected for their live options before an LLM answer is accepted. Unsupported layouts, security challenges, validation errors, and provider failures pause the visible browser for human action.
