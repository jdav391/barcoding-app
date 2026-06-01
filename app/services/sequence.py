from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import SequenceCounter

MAX_SEQUENCE_VALUE = 999_999_999


def claim_range(
    session: Session,
    count: int,
    counter_name: str = "global",
) -> tuple[int, int]:
    counter = session.query(SequenceCounter).filter_by(name=counter_name).first()
    if counter is None:
        counter = SequenceCounter(name=counter_name, last_value=0)
        session.add(counter)
        session.flush()

    start = counter.last_value + 1
    end = counter.last_value + count

    if end > MAX_SEQUENCE_VALUE:
        raise ValueError(
            f"Sequence counter '{counter_name}' would exceed {MAX_SEQUENCE_VALUE}. "
            "Reset the counter before continuing."
        )

    counter.last_value = end
    session.commit()
    return start, end


def get_current_value(
    session: Session,
    counter_name: str = "global",
) -> int:
    counter = session.query(SequenceCounter).filter_by(name=counter_name).first()
    if counter is None:
        return 0
    return counter.last_value


def reset_counter(
    session: Session,
    counter_name: str = "global",
) -> None:
    counter = session.query(SequenceCounter).filter_by(name=counter_name).first()
    if counter is not None:
        counter.last_value = 0
        session.commit()
