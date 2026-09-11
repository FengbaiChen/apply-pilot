from fastapi import APIRouter, Request, HTTPException
from app.api.schemas.application_request import ApplicationRequest, ResumeRequest, HumanAnswersRequest, ReviewApprovalRequest
from app.api.schemas.application_response import ApplicationResponse
from app.domain.application import ApplicationSession
from app.domain.review import ReviewReport

router = APIRouter()

@router.post("/applications", response_model=ApplicationResponse, status_code=202)
async def create_application(body: ApplicationRequest, request: Request):
    return await request.app.state.service.start(str(body.url),
        reference_prompt=body.reference_prompt, application_context=body.application_context, platform=body.platform)

@router.get("/capabilities")
async def capabilities(request: Request):
    return request.app.state.service.capabilities()

@router.post("/applications/{application_id}/answers", response_model=ApplicationResponse, status_code=202)
async def answer_questions(application_id: str, body: HumanAnswersRequest, request: Request):
    return await request.app.state.service.submit_answers(application_id, body.answers)

@router.get("/applications/{application_id}", response_model=ApplicationSession)
async def application_status(application_id: str, request: Request):
    return request.app.state.service.get(application_id)

@router.post("/applications/{application_id}/resume", response_model=ApplicationResponse)
async def resume_application(application_id: str, request: Request, body: ResumeRequest = ResumeRequest()):
    return await request.app.state.service.resume(application_id, body.confirm_current_values)

@router.post("/applications/{application_id}/stop", response_model=ApplicationResponse)
async def stop_application(application_id: str, request: Request):
    return await request.app.state.service.stop(application_id)

@router.get("/applications/{application_id}/review", response_model=ReviewReport)
async def application_review(application_id: str, request: Request):
    report = request.app.state.service.get(application_id).review
    if report is None: raise HTTPException(409, "No audit is available yet")
    return report


@router.post("/applications/{application_id}/review/approve", response_model=ApplicationResponse)
async def approve_review(application_id: str, body: ReviewApprovalRequest, request: Request):
    return await request.app.state.service.approve_review(application_id, body.answers)
