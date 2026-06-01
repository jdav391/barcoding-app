from app.services.sequence import claim_range, get_current_value, reset_counter
from app.models import SequenceCounter


class TestClaimRange:
    def test_first_claim_starts_at_1(self, db_session):
        start, end = claim_range(db_session, count=10)
        assert start == 1
        assert end == 10

    def test_second_claim_continues(self, db_session):
        claim_range(db_session, count=10)
        start, end = claim_range(db_session, count=5)
        assert start == 11
        assert end == 15

    def test_claim_single(self, db_session):
        start, end = claim_range(db_session, count=1)
        assert start == 1
        assert end == 1

    def test_named_counter(self, db_session):
        start1, _ = claim_range(db_session, count=5, counter_name="batch_a")
        start2, _ = claim_range(db_session, count=5, counter_name="batch_b")
        assert start1 == 1
        assert start2 == 1

    def test_persists_across_calls(self, db_session):
        claim_range(db_session, count=100)
        value = get_current_value(db_session)
        assert value == 100


class TestResetCounter:
    def test_reset_to_zero(self, db_session):
        claim_range(db_session, count=50)
        reset_counter(db_session)
        start, end = claim_range(db_session, count=1)
        assert start == 1

    def test_overflow_detection(self, db_session):
        counter = SequenceCounter(name="global", last_value=999_999_998)
        db_session.add(counter)
        db_session.commit()
        start, end = claim_range(db_session, count=1)
        assert start == 999_999_999
        assert end == 999_999_999
