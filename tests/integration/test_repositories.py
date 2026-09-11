from app.repositories.database import Database
from app.repositories.answer_repository import AnswerRepository
from app.repositories.application_repository import ApplicationRepository
from app.domain.answer import Answer
from app.domain.application import ApplicationSession
from app.domain.enums import AnswerSource, ApplicationState

def test_only_explicit_approval_and_exact_scope_are_reused(tmp_path):
    db=Database(tmp_path/'test.sqlite'); repo=AnswerRepository(db)
    try:
        answer_id=repo.save('Why this role?','why this role',Answer(value='Draft',source=AnswerSource.LLM,confidence=.8),company='employer-a',role='engineer')
        assert repo.find_approved('why this role','employer-a','engineer') is None
        assert repo.approve(answer_id)
        assert repo.find_approved('why this role','employer-b','engineer') is None
        a=repo.find_approved('why this role','employer-a','engineer')
        assert a.value == 'Draft' and a.source == AnswerSource.ANSWER_BANK
        row=db.connection.execute('SELECT * FROM answers WHERE id=?',(answer_id,)).fetchone()
        assert row['times_used'] == 1 and row['approved_by_user'] == 1
    finally: db.close()

def test_session_persistence_and_interrupted_recovery(tmp_path):
    db=Database(tmp_path/'test.sqlite'); repo=ApplicationRepository(db)
    session=ApplicationSession(url='https://example.test',status=ApplicationState.RUNNING)
    repo.save(session); db.close()
    db=Database(tmp_path/'test.sqlite'); repo=ApplicationRepository(db)
    try:
        assert repo.get(session.application_id).status == ApplicationState.RUNNING
        repo.recover_interrupted()
        assert repo.get(session.application_id).status == ApplicationState.STOPPED
        assert repo.get('missing') is None
    finally: db.close()
