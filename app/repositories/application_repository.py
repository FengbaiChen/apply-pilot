from app.domain.application import ApplicationSession
from app.domain.enums import ApplicationState
from app.repositories.database import Database

class ApplicationRepository:
    def __init__(self, db: Database): self.db = db

    def save(self, session: ApplicationSession):
        with self.db.connection:
            self.db.connection.execute("INSERT OR REPLACE INTO applications VALUES (?, ?)",
                                       (session.application_id, session.model_dump_json()))

    def get(self, application_id: str) -> ApplicationSession | None:
        row = self.db.connection.execute("SELECT payload FROM applications WHERE id=?", (application_id,)).fetchone()
        return ApplicationSession.model_validate_json(row[0]) if row else None

    def recover_interrupted(self):
        for row in self.db.connection.execute("SELECT payload FROM applications").fetchall():
            session = ApplicationSession.model_validate_json(row[0])
            if session.status not in {ApplicationState.STOPPED, ApplicationState.FAILED}:
                session.status = ApplicationState.STOPPED
                session.pending_questions = []
                session.current_action = "Server restarted; browser session no longer attached. Start a new application."
                self.save(session)
