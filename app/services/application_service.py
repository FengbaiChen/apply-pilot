import asyncio
import logging
from datetime import datetime, timezone
from app.domain.application import ApplicationSession
from app.domain.answer import Answer
from app.domain.enums import ApplicationState as State, AnswerSource
from app.services.validation_service import is_blank
from app.workers.browser_worker import BrowserWorker
from app.services.human_question_service import HumanQuestionService, InvalidHumanAnswer
from app.services.question_normalizer import normalized_text

logger = logging.getLogger(__name__)

class SessionConflict(ValueError): pass

class ApplicationService:
    def __init__(self, settings, repository, answers, inspection, fill, validation, navigation, review,
                 registry, detector, worker_factory=BrowserWorker):
        self.settings, self.repository, self.answers = settings, repository, answers
        self.inspection, self.fill, self.validation = inspection, fill, validation
        self.navigation, self.review_service = navigation, review
        self.registry, self.detector, self.worker_factory = registry, detector, worker_factory
        self.session = None
        self.worker = None
        self.adapter = None
        self.task = None
        self.evidence = {}
        self.current_page_keys = set()
        self.resolved = {}
        self.lock = asyncio.Lock()
        self.human_questions = HumanQuestionService(answers, fill.confidence)
        self.question_fields = {}
        self.pending_approvals = []
        self.job_context_extracted = False

    def capabilities(self):
        return {
            "llm_configured": self.answers.llm is not None,
            "llm_connection_tested": False,
            "llm_message": "LLM configured; provider connectivity has not been tested."
                if self.answers.llm else "LLM is unavailable. Unknown required questions will pause for your answer.",
        }

    def _update(self, state=None, action=None, message=None):
        if state: self.session.status = state
        if action: self.session.current_action = action
        self.session.human_message = message
        self.session.updated_at = datetime.now(timezone.utc)
        self.repository.save(self.session)
        logger.info("application=%s state=%s action=%s", self.session.application_id,
                    self.session.status, self.session.current_action)

    async def start(self, url, reference_prompt="", application_context="", platform="workday"):
        async with self.lock:
            if self.worker is not None: raise SessionConflict("Stop and close the current browser before starting another application.")
            if platform != "workday":
                raise SessionConflict("Only Workday applications are supported.")
            try:
                self.answers.profile.validate_workday()
            except ValueError as exc:
                raise SessionConflict(str(exc))
            self.session = ApplicationSession(url=url, reference_prompt=reference_prompt,
                                              application_context=application_context, platform=platform)
            self.evidence, self.resolved = {}, {}
            self.current_page_keys = set()
            self.question_fields = {}
            self.pending_approvals = []
            self.job_context_extracted = False
            self.worker = self.worker_factory(self.settings)
            self.adapter = None
            self.repository.save(self.session)
            self.task = asyncio.create_task(self._run(open_page=True), name=self.session.application_id)
            return self.session.model_copy(deep=True)

    async def submit_answers(self, application_id, responses):
        async with self.lock:
            self.get(application_id)
            if (not self.session or self.session.application_id != application_id
                    or self.session.status != State.WAITING_FOR_HUMAN):
                raise SessionConflict("Only the active paused application accepts answers.")
            if self.task and not self.task.done():
                raise SessionConflict("The application is still pausing. Try again shortly.")
            requested = [response.question_id for response in responses]
            if (not self.question_fields or len(set(requested)) != len(requested)
                    or set(requested) != set(self.question_fields)):
                raise InvalidHumanAnswer("Answer all currently displayed questions exactly once; refresh if they changed.")
            if await self.adapter.security_challenge():
                raise SessionConflict("Complete the security check in the browser, then Resume.")
            # The user may have navigated or edited the browser while answering.
            live = await self.adapter.scan_fields()
            updates = {}
            replies = []
            for response in responses:
                snapshot = self.question_fields[response.question_id]
                matches = [f for f in live if f.key == snapshot.key]
                if len(matches) != 1:
                    raise SessionConflict("The application page changed. Click Resume to refresh its questions.")
                current = matches[0]
                if (current.question != snapshot.question or current.field_type != snapshot.field_type
                        or current.current_value != snapshot.current_value or not current.enabled
                        or current.locator.read_only):
                    raise SessionConflict("A browser field changed. Click Resume to refresh its questions.")
                known = self.answers.deterministic(current)
                if known is not None and known.value is not None:
                    raise InvalidHumanAnswer("A supplied answer cannot override an existing profile fact.")
                updates[current.key] = self.human_questions.validate(current, response.value)
                replies.append((current, updates[current.key]))
            # Validate the whole batch before accepting any answer.
            # Keep human replies in this session until final Review approval.
            # This prevents an abandoned application from silently changing the profile.
            self.pending_approvals.extend(replies)
            self.resolved.update(updates)
            self.session.pending_questions = []
            self.question_fields = {}
            self._update(State.RUNNING, "Applying your answers and continuing")
            self.task = asyncio.create_task(self._run())
            return self.session.model_copy(deep=True)

    def get(self, application_id):
        result = self.repository.get(application_id)
        if result is None: raise KeyError(application_id)
        return result

    async def resume(self, application_id, confirm_current_values=False):
        async with self.lock:
            self.get(application_id)
            if not self.session or self.session.application_id != application_id or self.session.status != State.WAITING_FOR_HUMAN:
                raise SessionConflict("Only the active session waiting for human action can resume.")
            if self.task and not self.task.done(): raise SessionConflict("Session is still pausing; try again shortly.")
            self._update(State.RUNNING, "Resuming after human action")
            self.task = asyncio.create_task(self._run(confirm_current_values=confirm_current_values))
            return self.session.model_copy(deep=True)

    async def stop(self, application_id):
        async with self.lock:
            self.get(application_id)
            if not self.session or self.session.application_id != application_id:
                raise SessionConflict("This session has no attached browser.")
            if self.task and not self.task.done():
                self.task.cancel()
                try: await self.task
                except asyncio.CancelledError: pass
            if self.worker: await self.worker.close()
            self.worker = None
            self.session.pending_questions = []
            self.question_fields = {}
            self._update(State.STOPPED, "Automation stopped and browser closed")
            return self.session.model_copy(deep=True)

    async def shutdown(self):
        if self.worker and self.session: await self.stop(self.session.application_id)

    def _pause(self, message):
        self._update(State.WAITING_FOR_HUMAN, "Waiting for human action", message)

    async def prepare_page(self):
        return True

    async def _run(self, open_page=False, confirm_current_values=False):
        try:
            self._update(State.RUNNING, "Opening application" if open_page else "Inspecting current page")
            self.session.pending_questions = []
            self.question_fields = {}
            if open_page: await self.worker.open(self.session.url)
            self.adapter = self.registry.create(self.session.platform, self.worker)
            if confirm_current_values:
                for f in await self.adapter.scan_fields():
                    expected = self.answers.deterministic(f)
                    if not is_blank(f) and (expected is None or expected.value is None):
                        self.resolved[f.key] = Answer(value=f.current_value, source=AnswerSource.HUMAN,
                            confidence=1, requires_review=False, reason="User explicitly confirmed this current browser value")
            for _ in range(self.settings.max_pages):
                self.session.review = None
                if not await self.prepare_page(): return
                challenge = await self.adapter.security_challenge()
                if challenge:
                    self._pause(challenge); return
                # Up to three passes handle dependent controls revealed by earlier answers.
                for repair_pass in range(3):
                    self._update(action="Scanning and verifying application fields")
                    fields = await self.adapter.scan_fields()
                    before = [(f.key, f.current_value) for f in fields]
                    for f in fields:
                        if not f.enabled and not f.current_value: continue
                        if (not f.required and is_blank(f) and self.answers.deterministic(f) is None
                                and self.answers.cached(f, company=self.session.url) is None): continue
                        answer = self.resolved.get(f.key)
                        if answer is None:
                            selectable = f.required and f.field_type.value in {"select", "autocomplete", "radio", "multiselect"}
                            if selectable:
                                # First resolve deterministic/profile/history
                                # answers without opening a searchable control.
                                # Workday source prompts only reveal options
                                # after the known LinkedIn value is searched.
                                answer = await self.answers.resolve(f, company=self.session.url,
                                    reference_prompt=self.session.reference_prompt,
                                    application_context=self.session.application_context,
                                    allow_llm=False)
                                if answer.value is None:
                                    # Unknown required options must be inspected
                                    # before asking the LLM to choose a label.
                                    f = await self.inspection.inspect(f, self.adapter)
                                    if not f.options:
                                        answer = Answer(reason="Workday did not expose a usable option list; please answer this required field manually.")
                                    else:
                                        answer = await self.answers.resolve(f, company=self.session.url,
                                            reference_prompt=self.session.reference_prompt,
                                            application_context=self.session.application_context)
                            else:
                                answer = await self.answers.resolve(f, company=self.session.url,
                                    reference_prompt=self.session.reference_prompt,
                                    application_context=self.session.application_context)
                            self.resolved[f.key] = answer
                        if self.answers.matches(f, answer): continue
                        if answer.value is not None:
                            self._update(action="Inspecting and filling a field")
                            f = await self.inspection.inspect(f, self.adapter, str(answer.value))
                            try:
                                await self.fill.fill(f, answer, self.adapter)
                            except Exception:
                                logger.info("application=%s field interaction requires human action", self.session.application_id)
                    fields = await self.adapter.scan_fields()
                    if before == [(f.key, f.current_value) for f in fields]: break
                challenge = await self.adapter.security_challenge()
                if challenge:
                    self._pause(challenge); return
                errors = await self.adapter.get_validation_errors()
                # Replace evidence for this page to discard fields removed by conditional UI.
                if fields:
                    self.evidence = {k:v for k,v in self.evidence.items() if k not in self.current_page_keys}
                    self.evidence.update({f.key:f for f in fields})
                    self.current_page_keys = {f.key for f in fields}
                findings = self.validation.validate(fields, self.resolved, errors)
                self.session.pending_questions, self.question_fields = self.human_questions.collect(fields, self.resolved)
                if self.session.pending_questions:
                    self.session.review = self.review_service.audit(fields, self.resolved, errors)
                    self._pause("Please answer the questions below and choose Save answers & continue. Your browser will remain open.")
                    return
                final_stage = await self.adapter.is_review_page()
                if final_stage:
                    self.session.review = self.review_service.audit(list(self.evidence.values()), self.resolved,
                        errors, prior_page_count=self.session.pages_processed)
                    if self.session.review.ready:
                        self._update(State.READY_FOR_REVIEW, "Final audit ready. Review the employer page and submit manually.")
                    else:
                        self._pause("Final audit found unresolved errors. Correct the browser fields (or profile and restart). Confirm manually supplied values if needed, then Resume.")
                    return
                if not self.validation.can_navigate(findings):
                    self.session.review = self.review_service.audit(fields, self.resolved, errors)
                    self._pause("Required, mismatched or unverified values need attention. Review the findings, correct fields in the browser, and Resume. Select the confirmation checkbox for manually supplied answers.")
                    return
                if not fields:
                    self._pause("No supported application fields found. Open the application form manually, then Resume."); return
                self._update(action="Validation passed; looking for the next step")
                old_signature = [(f.key, f.question) for f in fields]
                if not await self.navigation.advance(self.adapter):
                    self._pause("No unambiguous safe Next/Continue control. Navigate to the next application step manually, then Resume."); return
                self.session.pages_processed += 1
                self.current_page_keys = set()
                next_fields = await self.adapter.scan_fields()
                if [(f.key, f.question) for f in next_fields] == old_signature and not await self.adapter.is_review_page():
                    self._pause("Navigation did not reach a new application step. Check the browser for validation or loading issues, then Resume."); return
            self._pause("Page iteration limit reached. Check the current browser state before resuming.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Error messages from browser/providers may contain sensitive URL or field data.
            logger.error("application=%s failed error_type=%s", self.session.application_id, type(exc).__name__)
            self._update(State.FAILED, "Automation failed; browser remains available if it launched.",
                         "Check browser installation, profile lock and page availability. Stop this session before retrying.")

    async def approve_review(self, application_id, edits):
        """Apply local review edits, then persist only the approved answers."""
        async with self.lock:
            self.get(application_id)
            if not self.session or self.session.application_id != application_id:
                raise SessionConflict("This application has no attached browser.")
            if self.session.status != State.READY_FOR_REVIEW:
                raise SessionConflict("Only an application ready for review can be approved.")
            if not self.worker or not self.adapter:
                raise SessionConflict("The browser is no longer attached to this application.")
            live = await self.adapter.scan_fields()
            by_id = {f.id: f for f in live}
            replies = []
            for edit in edits:
                field = by_id.get(edit.field_id) or next((f for f in self.evidence.values() if f.id == edit.field_id), None)
                if field is None:
                    raise InvalidHumanAnswer("The Review page changed; refresh the audit and try again.")
                # Review summaries are often read-only elements with a fresh
                # token. Resolve them to the original editable evidence before
                # walking back through the Workday wizard.
                review_summary = field.locator.read_only
                if review_summary:
                    same_question = [f for f in self.evidence.values()
                                     if not f.locator.read_only
                                     and normalized_text(f.question) == normalized_text(field.question)]
                    same_section = [f for f in same_question
                                    if normalized_text(f.section) == normalized_text(field.section)]
                    original = (same_section[0] if len(same_section) == 1
                                else same_question[0] if len(same_question) == 1 else None)
                    field = original or field
                answer = HumanQuestionService.validate(field, edit.value)
                if review_summary or field.locator.read_only or not by_id.get(edit.field_id):
                    # Review summaries are read-only and older wizard controls
                    # are no longer mounted. Walk back to the recorded step,
                    # edit the real control, and safely walk forward again.
                    field = await self._edit_previous_step(field, answer)
                else:
                    field = await self.inspection.inspect(field, self.adapter, str(answer.value))
                    if not await self.fill.fill(field, answer, self.adapter):
                        raise InvalidHumanAnswer("The edited value could not be applied to the Workday control.")
                    field.current_value = answer.value
                self.evidence[field.key] = field
                self.resolved[field.key] = answer
            # Answers from earlier Workday pages remain in evidence and are
            # approved together with the final-page values.
            all_fields = list({f.key: f for f in [*self.evidence.values(), *live]}.values())
            for field in all_fields:
                answer = self.resolved.get(field.key)
                if answer is not None:
                    replies.append((field, answer))
            replies.extend(self.pending_approvals)
            unique = {}
            for field, answer in replies:
                value_key = tuple(answer.value) if isinstance(answer.value, list) else answer.value
                unique[(field.key, value_key)] = (field, answer)
            replies = list(unique.values())
            self.answers.remember_approved(replies, company=self.session.url)
            refreshed = await self.adapter.scan_fields()
            errors = await self.adapter.get_validation_errors()
            audited = list({f.key: f for f in [*self.evidence.values(), *refreshed]}.values())
            self.session.review = self.review_service.audit(audited, self.resolved, errors,
                                                            prior_page_count=self.session.pages_processed)
            self._update(State.READY_FOR_REVIEW,
                         "Review approved and answers saved. Submit manually in Workday.")
            return self.session.model_copy(deep=True)

    async def _edit_previous_step(self, evidence_field, answer):
        fragment = evidence_field.page_url.split('#', 1)[1] if '#' in evidence_field.page_url else ''
        target = normalized_text(fragment)
        if not target:
            raise InvalidHumanAnswer("This answer has no recorded Workday step; refresh the audit and try again.")
        headings = {'my information', 'my experience', 'application questions', 'voluntary disclosures', 'review'}
        for _ in range(6):
            current = [normalized_text(x) for x in await self.worker.page.locator('h2:visible,h3:visible,[role=heading]:visible').all_inner_texts()]
            if target in current:
                fields = await self.adapter.scan_fields()
                candidates = [f for f in fields if normalized_text(f.question) == normalized_text(evidence_field.question)
                              and normalized_text(f.section) == normalized_text(evidence_field.section)]
                if len(candidates) != 1:
                    raise InvalidHumanAnswer("The recorded Workday control is no longer unique; edit it in the browser.")
                field = await self.inspection.inspect(candidates[0], self.adapter, str(answer.value))
                if not await self.fill.fill(field, answer, self.adapter):
                    raise InvalidHumanAnswer("The edited value could not be applied to the Workday control.")
                field.current_value = answer.value
                while not await self.adapter.is_review_page():
                    if not await self.navigation.advance(self.adapter):
                        raise InvalidHumanAnswer("Workday could not return to Review after editing this answer.")
                return field
            if any(x == 'review' for x in current) and target not in headings:
                break
            back = self.worker.page.get_by_role('button', name='Back', exact=True)
            if await back.count() != 1 or not await back.is_visible():
                break
            await back.click()
            await self.worker.settle(autofill=True)
        raise InvalidHumanAnswer("Workday could not navigate back to the answer; edit it manually in the browser.")
