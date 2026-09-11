import re
from app.domain.enums import CanonicalQuestion as Q

def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold().strip()).rstrip(" ?*:.")

class QuestionNormalizer:
    def normalize(self, question: str) -> Q:
        q = normalized_text(question)
        # Narrow recognition: negated or compound questions need human interpretation.
        if re.search(r"\b(not|never|without|except)\b", q):
            return Q.UNKNOWN
        if ("sponsor" in q or "visa" in q or "work permit" in q or "employer support" in q) and re.search(r"require|need|support", q):
            return Q.REQUIRES_SPONSORSHIP
        if re.search(r"(authori[sz]ed|eligible|legal(?:ly)?|right).*(work|employment)", q):
            return Q.AUTHORIZED_TO_WORK
        if re.search(r"willing.*relocat|open to relocat|^relocation$", q):
            return Q.WILLING_TO_RELOCATE
        if re.fullmatch(r"(school|school name|university|university name|college|institution|institution name|(?:school|college)\s*(?:/|or)\s*university)", q):
            return Q.SCHOOL
        if re.fullmatch(r"(major|field of study|primary major|area of study)", q):
            return Q.MAJOR
        if re.fullmatch(r"(degree|degree type|education level|highest degree)", q):
            return Q.DEGREE
        if re.search(r"graduat.*(date|month|year)|^(graduation|expected graduation)$", q):
            return Q.GRADUATION_DATE
        return Q.UNKNOWN

    def bank_key(self, question: str) -> str:
        # Exact normalized text avoids conflating differently qualified questions.
        return normalized_text(question)
