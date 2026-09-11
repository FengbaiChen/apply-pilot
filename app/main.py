import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.ats.registry import AdapterRegistry
from app.config.profile import Profile
from app.config.settings import Settings
from app.config.prompts import load_reference_prompt
from app.repositories.database import Database
from app.repositories.application_repository import ApplicationRepository
from app.repositories.answer_repository import AnswerRepository
from app.services.application_service import ApplicationService, SessionConflict
from app.services.human_question_service import InvalidHumanAnswer
from app.repositories.profile_answer_repository import ProfileSaveError
from app.services.field_fill_service import FieldFillService
from app.services.field_inspection_service import FieldInspectionService
from app.services.navigation_service import NavigationService
from app.services.option_collector import OptionCollector
from app.services.review_service import ReviewService
from app.services.validation_service import ValidationService
from app.api.controllers.application_controller import router

WEB = Path(__file__).parent / "web"

def build_service(settings):
    db = Database(settings.database_path)
    repository = ApplicationRepository(db)
    repository.recover_interrupted()
    profile_path = Path(os.getenv("APPLY_PILOT_PROFILE", "config/profile.yaml"))
    profile = Profile.load(profile_path)
    llm = None
    if settings.llm_enabled and os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL"):
        from app.integrations.llm.openai_client import OpenAICompatibleClient
        llm = OpenAICompatibleClient(os.environ['LLM_API_KEY'], os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1'), os.environ['LLM_MODEL'])
    from app.services.application_dispatcher import ApplicationDispatcher
    from app.platforms.workday.service import WorkdayApplicationService
    from app.platforms.workday.answers import WorkdayAnswerService
    from app.platforms.workday.adapter import WorkdayATSAdapter

    def factory(platform):
        if platform != "workday":
            raise ValueError("Only the Workday platform is supported")
        answers = WorkdayAnswerService(profile, AnswerRepository(db), llm,
            reference_prompt=load_reference_prompt(settings.llm_prompt_path), profile_path=profile_path)
        validation = ValidationService(answers)
        registry = AdapterRegistry()
        registry.register("workday", WorkdayATSAdapter)
        return WorkdayApplicationService(settings, repository, answers,
            FieldInspectionService(OptionCollector(settings.max_option_iterations, settings.option_stale_limit)),
            FieldFillService(answers), validation, NavigationService(), ReviewService(validation),
            registry, None)

    capabilities = factory("workday").capabilities()
    return ApplicationDispatcher(repository, factory, capabilities), db

def create_app(service=None):
    @asynccontextmanager
    async def lifespan(app):
        load_dotenv()
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        db = None
        if service is None: app.state.service, db = build_service(Settings.load())
        else: app.state.service = service
        try: yield
        finally:
            await app.state.service.shutdown()
            if db: db.close()

    app = FastAPI(title="ApplyPilot", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_request_guard(request: Request, call_next):
        origin = request.headers.get('origin')
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != str(request.base_url).rstrip('/')):
                return JSONResponse({"detail": "Cross-origin control requests are rejected"}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(KeyError)
    async def not_found(request, exc): return JSONResponse({"detail": "Application not found"}, status_code=404)
    @app.exception_handler(SessionConflict)
    async def conflict(request, exc): return JSONResponse({"detail": str(exc)}, status_code=409)
    @app.exception_handler(InvalidHumanAnswer)
    async def invalid_answer(request, exc): return JSONResponse({"detail": str(exc)}, status_code=422)
    @app.exception_handler(ProfileSaveError)
    async def profile_save_failed(request, exc): return JSONResponse({"detail": str(exc)}, status_code=503)

    app.include_router(router)
    app.mount('/static', StaticFiles(directory=WEB / 'static'), name='static')
    @app.get('/', include_in_schema=False)
    async def index(): return FileResponse(WEB / 'templates/index.html')
    return app

app = create_app()
