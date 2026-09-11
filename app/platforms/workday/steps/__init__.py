from .my_information import MyInformationStep
from .my_experience import MyExperienceStep
from .application_questions import ApplicationQuestionsStep
from .voluntary_disclosures import VoluntaryDisclosuresStep
from .review import ReviewStep
from app.services.question_normalizer import normalized_text

STEPS = {step.key: step for step in [MyInformationStep(), MyExperienceStep(),
    ApplicationQuestionsStep(), VoluntaryDisclosuresStep(), ReviewStep()]}
BY_HEADING = {normalized_text(step.heading): step for step in STEPS.values()}
