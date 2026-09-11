import json
from app.domain.answer import Answer
from app.domain.enums import AnswerSource
from app.repositories.database import Database

class AnswerRepository:
    def __init__(self, db: Database): self.db = db

    def find_approved(self, question: str, company: str = "", role: str = "") -> Answer | None:
        # Scope must match exactly. Company-specific prose cannot leak to another application.
        row = self.db.connection.execute("""SELECT * FROM answers WHERE normalized_question=?
            AND approved_by_user=1 AND company=? AND role=? ORDER BY updated_at DESC, id DESC LIMIT 1""",
            (question, company, role)).fetchone()
        if not row: return None
        with self.db.connection:
            self.db.connection.execute("UPDATE answers SET times_used=times_used+1 WHERE id=?", (row['id'],))
        return Answer(value=json.loads(row['answer']), source=AnswerSource.ANSWER_BANK,
                      confidence=row['confidence'], requires_review=row['confidence'] < .9,
                      reason="Explicitly approved historical answer", bank_id=row['id'])

    def save(self, original: str, normalized: str, answer: Answer, company: str = "", role: str = "",
             approved: bool = False, answer_type: str = "text") -> int:
        with self.db.connection:
            cursor = self.db.connection.execute("""INSERT INTO answers
                (original_question,normalized_question,answer,answer_type,company,role,confidence,approved_by_user)
                VALUES (?,?,?,?,?,?,?,?)""", (original, normalized, json.dumps(answer.value), answer_type,
                company, role, answer.confidence, int(approved)))
        return cursor.lastrowid

    def approve(self, answer_id: int) -> bool:
        with self.db.connection:
            cursor = self.db.connection.execute("UPDATE answers SET approved_by_user=1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (answer_id,))
        return cursor.rowcount == 1

    def list_unapproved(self) -> list[dict]:
        return [dict(row) for row in self.db.connection.execute(
            "SELECT id,original_question,answer,company,role FROM answers WHERE approved_by_user=0 ORDER BY id DESC")]
