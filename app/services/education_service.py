import calendar
from app.config.profile import Profile
from app.domain.enums import CanonicalQuestion as Q
from app.services.question_normalizer import normalized_text

class EducationService:
    def __init__(self, profile: Profile):
        self.education = profile.education

    def expected(self, key: Q, question: str = "") -> str | None:
        e = self.education
        if key == Q.SCHOOL: return e.school
        if key == Q.MAJOR: return e.major
        if key == Q.DEGREE: return e.degree
        if key == Q.GRADUATION_DATE:
            q = question.lower()
            if "year" in q and "month" not in q:
                return str(e.graduation_year) if e.graduation_year else None
            if "month" in q and "year" not in q:
                return str(e.graduation_month) if e.graduation_month else None
            if e.graduation_year and e.graduation_month:
                return f"{e.graduation_year:04d}-{e.graduation_month:02d}"
        return None

    def aliases(self, key: Q, question: str = "") -> list[str]:
        value = self.expected(key, question)
        values = [value] if value else []
        if key == Q.SCHOOL: values += self.education.school_aliases
        if key == Q.MAJOR: values += self.education.major_aliases
        if key == Q.GRADUATION_DATE and value and "month" in question.lower() and "year" not in question.lower():
            month = self.education.graduation_month
            values += [f"{month:02d}", calendar.month_name[month], calendar.month_abbr[month]]
        return values

    def matches(self, key: Q, value: object, question: str = "") -> bool:
        if not isinstance(value, str): return False
        v = normalized_text(value)
        if key == Q.SCHOOL and v in {normalized_text(x) for x in self.education.unsafe_school_matches}:
            return False
        return v in {normalized_text(x) for x in self.aliases(key, question)}
