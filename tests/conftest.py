import pytest

from agent.config import Settings
from agent.fake_llm import FakeLLM
from agent.graph import build_graph

ARTICLE = (
    "Most teams treat the weekly planning meeting as the place where work gets decided. "
    "In practice, the meeting is where decisions get announced.\n\n"
    "A small product team required a one-page written brief 24 hours before every meeting. "
    "Meetings dropped from 75 minutes to 30 on average.\n\n"
    "Reversed decisions in the following month fell from five to one. "
    "The one-page limit forced authors to get to the trade-off quickly."
)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(llm_provider="fake", schedule_file=str(tmp_path / "scheduled.json"))


@pytest.fixture
def fake_llm(settings) -> FakeLLM:
    return FakeLLM(settings)


@pytest.fixture
def graph(settings, fake_llm):
    return build_graph(settings=settings, llm=fake_llm)
