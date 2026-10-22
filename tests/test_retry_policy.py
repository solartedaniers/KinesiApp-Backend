from app.analysis.retry_policy import RetryPolicy
from app.settings.analysis import AnalysisSettings


def test_the_wait_grows_from_the_second_attempt_up_to_the_ceiling() -> None:
    policy = RetryPolicy(max_attempts=5, initial_delay=5, factor=2, max_delay=12)

    assert [policy.delay_before(attempt) for attempt in range(1, 6)] == [0, 5, 10, 12, 12]
    assert policy.allows(5) and not policy.allows(6)


def test_the_policy_comes_from_the_analysis_settings() -> None:
    settings = AnalysisSettings(_env_file=None, MAX_ATTEMPTS=2, RETRY_INITIAL_DELAY_SECONDS=1, RETRY_MAX_DELAY_SECONDS=3)

    assert RetryPolicy.from_settings(settings) == RetryPolicy(2, 1, 2.0, 3)
