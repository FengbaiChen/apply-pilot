import re
from pathlib import Path
from app.config.profile import Profile, SavedAnswer
from app.domain.answer import Answer
from app.domain.enums import AnswerSource as S, CanonicalQuestion as Q, FieldType
from app.domain.field import Field
from app.services.question_normalizer import QuestionNormalizer, normalized_text
from app.services.education_service import EducationService
from app.repositories.profile_answer_repository import ProfileAnswerRepository, saved_answer_key
from app.services.human_question_service import HumanQuestionService, InvalidHumanAnswer

PERSONAL_KEYS = {
    "full name": "full_name", "name": "full_name", "first name": "first_name", "given name": "first_name",
    "preferred name": "preferred_name", "nickname": "preferred_name",
    "last name": "last_name", "family name": "last_name", "email": "email", "email address": "email",
    "phone": "phone", "phone number": "phone", "mobile phone": "phone", "city": "city",
    "state": "state", "province": "state", "country": "country",
    "linkedin": "linkedin", "linkedin url": "linkedin", "linkedin profile": "linkedin",
    "linkedin profile url": "linkedin",
    "address line 1": "address_line1", "street address": "address_line1",
    "postal code": "postal_code", "zip code": "postal_code", "zip": "postal_code",
}
EDUCATION_KEYS = {Q.SCHOOL, Q.MAJOR, Q.DEGREE, Q.GRADUATION_DATE}

class AnswerService:
    def __init__(self, profile: Profile, repository, llm=None, reference_prompt: str = "",
                 profile_path: Path | None = None):
        self.profile, self.repository, self.llm = profile, repository, llm
        self.normalizer = QuestionNormalizer()
        self.education = EducationService(profile)
        self.reference_prompt = reference_prompt
        self.profile_answers = ProfileAnswerRepository(profile, profile_path)

    def _saved_entry(self, field: Field, value, company: str) -> SavedAnswer:
        contextual = (self.is_free_form(field) or field.field_type == FieldType.TEXTAREA
                      or bool(re.search(r"\b(company|employer|position|role|agree|consent|certify|acknowledge)\b",
                                        normalized_text(field.question))))
        return SavedAnswer(question=field.question, field_type=field.field_type, value=value,
                           section=field.section, option_labels=[o.label for o in field.options],
                           application_url=company if contextual else "")

    def cached(self, field: Field, company: str = "") -> Answer | None:
        if field.field_type in {FieldType.FILE, FieldType.UNKNOWN}:
            return None
        key = saved_answer_key(self._saved_entry(field, "", company))
        for entry in reversed(self.profile.saved_answers):
            if saved_answer_key(entry) != key:
                continue
            try:
                answer = HumanQuestionService.validate(field, entry.value)
            except InvalidHumanAnswer:
                return None
            answer.source = S.PROFILE_CACHE
            answer.reason = "Explicit human answer saved in the local profile"
            return answer
        return None

    def remember(self, replies, company: str = ""):
        self.profile_answers.save([self._saved_entry(field, answer.value, company)
                                   for field, answer in replies if answer.source == S.HUMAN])

    def remember_approved(self, replies, company: str = ""):
        """Persist only answers explicitly approved on the final local review."""
        self.profile_answers.save([self._saved_entry(field, answer.value, company)
                                   for field, answer in replies
                                   if answer.source in {S.HUMAN, S.LLM, S.PROFILE_CACHE, S.ANSWER_BANK}])

    def deterministic(self, field: Field) -> Answer | None:
        q = self.normalizer.normalize(field.question)
        value = None
        source = S.PROFILE
        if q == Q.REQUIRES_SPONSORSHIP:
            value = self.profile.work_authorization.require_future_sponsorship
            source = S.RULE
        elif q == Q.AUTHORIZED_TO_WORK:
            # US-specific fact must never answer another country's question.
            text = normalized_text(field.question)
            if not re.search(r"\b(us|usa|u\.s\.?|united states)\b", text):
                return Answer(reason="Work authorization jurisdiction is not explicitly the United States.")
            value = self.profile.work_authorization.authorized_to_work_us
            source = S.RULE
        elif q == Q.WILLING_TO_RELOCATE:
            value = self.profile.preferences.willing_to_relocate
            source = S.RULE
        elif q in EDUCATION_KEYS:
            value = self.education.expected(q, field.question)
        elif normalized_text(field.question) in PERSONAL_KEYS:
            value = getattr(self.profile.personal, PERSONAL_KEYS[normalized_text(field.question)])
        elif normalized_text(field.question) in {"phone device type", "phone type"}:
            value = self.profile.phone.device_type
        elif normalized_text(field.question) in {"country phone code", "phone country code"}:
            value = self.profile.phone.country_code
        elif normalized_text(field.question) in {"github", "github url", "github profile url"}:
            value = self.profile.links.github
        elif normalized_text(field.question) in {"linkedin", "linkedin url", "linkedin profile url"}:
            value = self.profile.links.linkedin or self.profile.personal.linkedin
        elif field.field_type == FieldType.FILE and re.search(r"resume|résumé|cv\b", field.question, re.I):
            value = self.profile.application.resume_path
        elif normalized_text(field.question) in {"overall result (gpa)", "gpa", "overall result"}:
            value = self.profile.education.gpa
        elif normalized_text(field.question) in {"from", "from (month)", "from (year)"} and 'education' in normalized_text(field.section):
            value = self.profile.education.start_month if 'month' in normalized_text(field.question) else self.profile.education.start_year
        elif normalized_text(field.question) in {"to", "to (actual or expected)", "to (month)", "to (year)"} and 'education' in normalized_text(field.section):
            value = self.profile.education.graduation_month if 'month' in normalized_text(field.question) else self.profile.education.graduation_year
        else:
            return None
        if value is None or value == "":
            return Answer(reason="This factual profile value is missing; manual input is required.")
        if isinstance(value, bool) and field.field_type != FieldType.CHECKBOX:
            value = "Yes" if value else "No"
        return Answer(value=value, source=source, confidence=1, requires_review=False, reason="Profile rule match")

    def is_free_form(self, field: Field) -> bool:
        return field.field_type in {FieldType.TEXT, FieldType.TEXTAREA} and bool(re.search(
            r"^(why\b|describe your experience|tell us about (?:a|your) project|what (?:interests|excites|attracts) you|what are you interested)",
            normalized_text(field.question)))

    async def resolve(self, field: Field, company: str = "", role: str = "",
                      reference_prompt: str = "", application_context: str = "",
                      allow_llm: bool = True) -> Answer:
        answer = self.deterministic(field)
        if answer is not None and answer.value is not None: return answer
        cached = self.cached(field, company)
        if cached is not None: return cached
        key = self.normalizer.bank_key(field.question)
        bank = self.repository.find_approved(key, company, role)
        if bank is not None: return bank
        # A recognized profile fact that is missing is never guessed. It may
        # still use an already approved history entry, but otherwise pauses for
        # an explicit human value (authorization and protected disclosures in
        # particular must not be inferred).
        if answer is not None: return answer
        # Required unknown controls are also offered to the LLM.  The caller has
        # already inspected them, so option answers can be checked exactly.
        if allow_llm and self.llm and field.required and field.field_type not in {FieldType.FILE, FieldType.UNKNOWN}:
            try:
                prompt_question = field.question
                if field.options:
                    if field.field_type == FieldType.MULTISELECT:
                        prompt_question += "\nChoose one or more options, returning only exact labels separated by commas: " + ", ".join(o.label for o in field.options)
                    else:
                        prompt_question += "\nChoose exactly one of these options: " + ", ".join(o.label for o in field.options)
                value = await self.llm.generate(prompt_question, self.profile.prose_facts(),
                    reference_prompt=reference_prompt.strip() or self.reference_prompt,
                    application_context=application_context)
            except Exception:
                # Provider errors can contain credentials/URLs: do not log their payloads.
                return Answer(reason="Optional language provider failed; please answer manually.")
            if value is not None and not isinstance(value, str):
                return Answer(reason="LLM returned an answer with an unsupported field type; please answer manually.")
            if value:
                if field.options:
                    if field.field_type == FieldType.MULTISELECT:
                        raw_values = [x.strip() for x in re.split(r"[,\n]", value) if x.strip()]
                        matches = []
                        for raw in raw_values:
                            found = [o for o in field.options if normalized_text(o.label) == normalized_text(raw)]
                            if len(found) != 1 or any(found[0].label == x.label for x in matches):
                                return Answer(reason="LLM did not return exact options shown by Workday; please answer manually.")
                            matches.append(found[0])
                        if not matches:
                            return Answer(reason="LLM did not return an exact Workday option; please answer manually.")
                        value = [x.label for x in matches]
                    else:
                        matches = [o for o in field.options if normalized_text(o.label) == normalized_text(value)]
                        if len(matches) != 1:
                            return Answer(reason="LLM did not return one exact option shown by Workday; please answer manually.")
                        value = matches[0].label
                if field.field_type == FieldType.CHECKBOX:
                    lowered = normalized_text(value)
                    if lowered not in {"yes", "no", "true", "false"}:
                        return Answer(reason="LLM did not return a valid Yes/No checkbox answer; please answer manually.")
                    value = lowered in {"yes", "true"}
                if isinstance(value, str):
                    limit = self._answer_length_limit(field.question)
                    if limit is not None and len(value) > limit:
                        return Answer(reason=f"LLM answer exceeds the {limit}-character limit shown by Workday; please answer manually.")
                    word_match = re.search(r"(?:at most|maximum|max(?:imum)?(?: of)?|limit(?:ed)? to)\s+(\d+)\s+words?", normalized_text(field.question))
                    if word_match and len(value.split()) > int(word_match.group(1)):
                        return Answer(reason=f"LLM answer exceeds the {word_match.group(1)}-word limit shown by Workday; please answer manually.")
                model = getattr(self.llm, "model", None)
                if not isinstance(model, str):
                    model = None
                answer = Answer(value=value, source=S.LLM, confidence=.8, requires_review=True,
                                model=model,
                                basis="Profile work/education facts + current job page context",
                                inferred=True,
                                reason="LLM draft based on profile and job context; tentative inference where no direct fact was configured; verify every claim")
                # Do not put an unapproved draft in the durable answer bank.
                # The final, user-approved version is written atomically to
                # profile.yaml by remember_approved().
                return answer
        return Answer(reason="No usable LLM answer is available; please answer and explicitly confirm the value.")

    @staticmethod
    def _answer_length_limit(question: str) -> int | None:
        """Read an explicit character limit without guessing an employer rule."""
        text = normalized_text(question)
        patterns = (
            r"(?:at most|maximum|max(?:imum)?(?: of)?|limit(?:ed)? to)\s+(\d+)\s+characters?",
            r"(\d+)\s+characters?\s*(?:maximum|or less|limit)",
        )
        limits = [int(m.group(1)) for pattern in patterns if (m := re.search(pattern, text))]
        return min(limits) if limits else None

    def matches(self, field: Field, answer: Answer) -> bool:
        q = self.normalizer.normalize(field.question)
        if q in EDUCATION_KEYS and answer.source not in {S.HUMAN, S.PROFILE_CACHE}:
            return self.education.matches(q, field.current_value, field.question)
        if field.field_type == FieldType.FILE:
            from pathlib import Path
            import hashlib
            if answer.source == S.HUMAN:
                return field.current_value == answer.value
            if not answer.value: return False
            path = Path(str(answer.value))
            if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024: return False
            return field.attachment_hashes.get(path.name) == hashlib.sha256(path.read_bytes()).hexdigest()
        if isinstance(answer.value, bool): return field.current_value is answer.value
        if isinstance(answer.value, list): return field.current_value == answer.value
        if answer.value is None or field.current_value is None: return False
        if normalized_text(field.question) in {"phone", "phone number", "mobile phone"}:
            return re.sub(r"\D", "", str(field.current_value)) == re.sub(r"\D", "", str(answer.value))
        return normalized_text(str(field.current_value)) == normalized_text(str(answer.value))

    def acceptable_labels(self, field: Field, answer: Answer) -> list[str]:
        if answer.source in {S.HUMAN, S.PROFILE_CACHE}:
            return answer.value if isinstance(answer.value, list) else [str(answer.value)]
        q = self.normalizer.normalize(field.question)
        if q in EDUCATION_KEYS:
            return [x for x in self.education.aliases(q, field.question) if self.education.matches(q, x, field.question)]
        return [str(answer.value)]
