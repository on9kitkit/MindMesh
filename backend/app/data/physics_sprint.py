from app.domain.constants import PHYSICS_SPRINT_BANK_KEY, QUESTION_DURATION_SECONDS
from app.domain.question import QuestionDefinition, QuestionOption

PHYSICS_SPRINT_QUESTIONS: tuple[QuestionDefinition, ...] = (
    QuestionDefinition(
        bank_key=PHYSICS_SPRINT_BANK_KEY,
        stable_key="physics-1",
        position=0,
        prompt="What is the SI unit of force?",
        options=(
            QuestionOption(id="joule", label="Joule"),
            QuestionOption(id="newton", label="Newton"),
            QuestionOption(id="watt", label="Watt"),
            QuestionOption(id="pascal", label="Pascal"),
        ),
        correct_option_id="newton",
        duration_seconds=QUESTION_DURATION_SECONDS,
    ),
    QuestionDefinition(
        bank_key=PHYSICS_SPRINT_BANK_KEY,
        stable_key="physics-2",
        position=1,
        prompt="What is the approximate speed of light in a vacuum?",
        options=(
            QuestionOption(id="light-1", label="3.0 × 10⁶ m/s"),
            QuestionOption(id="light-2", label="3.0 × 10⁸ m/s"),
            QuestionOption(id="light-3", label="3.0 × 10¹⁰ m/s"),
            QuestionOption(id="light-4", label="3.0 × 10¹² m/s"),
        ),
        correct_option_id="light-2",
        duration_seconds=QUESTION_DURATION_SECONDS,
    ),
    QuestionDefinition(
        bank_key=PHYSICS_SPRINT_BANK_KEY,
        stable_key="physics-3",
        position=2,
        prompt="Which law explains why an object at rest stays at rest?",
        options=(
            QuestionOption(id="first-law", label="Newton's first law"),
            QuestionOption(id="second-law", label="Newton's second law"),
            QuestionOption(id="third-law", label="Newton's third law"),
            QuestionOption(id="gravity-law", label="The law of gravitation"),
        ),
        correct_option_id="first-law",
        duration_seconds=QUESTION_DURATION_SECONDS,
    ),
    QuestionDefinition(
        bank_key=PHYSICS_SPRINT_BANK_KEY,
        stable_key="physics-4",
        position=3,
        prompt="What type of energy is stored in a stretched spring?",
        options=(
            QuestionOption(id="kinetic", label="Kinetic energy"),
            QuestionOption(id="thermal", label="Thermal energy"),
            QuestionOption(id="elastic", label="Elastic potential energy"),
            QuestionOption(id="nuclear", label="Nuclear energy"),
        ),
        correct_option_id="elastic",
        duration_seconds=QUESTION_DURATION_SECONDS,
    ),
    QuestionDefinition(
        bank_key=PHYSICS_SPRINT_BANK_KEY,
        stable_key="physics-5",
        position=4,
        prompt="What is the approximate acceleration due to gravity near Earth's surface?",
        options=(
            QuestionOption(id="gravity-1", label="0.98 m/s²"),
            QuestionOption(id="gravity-2", label="9.8 m/s²"),
            QuestionOption(id="gravity-3", label="98 m/s²"),
            QuestionOption(id="gravity-4", label="980 m/s²"),
        ),
        correct_option_id="gravity-2",
        duration_seconds=QUESTION_DURATION_SECONDS,
    ),
)

__all__ = ["PHYSICS_SPRINT_QUESTIONS"]
