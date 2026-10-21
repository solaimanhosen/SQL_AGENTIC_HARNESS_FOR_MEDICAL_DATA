import pytest

from sql_agent.agent import Turn
from sql_agent.conversations import ConversationBusy, ConversationStore, UnknownConversation


def _turn(number: int) -> Turn:
    return Turn(question=f"question {number}", answer=f"answer {number}")


def test_a_new_conversation_starts_empty_and_busy():
    store = ConversationStore()
    conversation_id, history, turn = store.begin(None)
    assert len(conversation_id) == 32 and history == () and turn == 1
    with pytest.raises(ConversationBusy):
        store.begin(conversation_id)


def test_finished_turns_are_handed_to_the_next_question():
    store = ConversationStore()
    conversation_id, _, _ = store.begin(None)
    store.finish(conversation_id, _turn(1))
    _, history, turn = store.begin(conversation_id)
    assert history == (_turn(1),) and turn == 2


def test_only_the_most_recent_turns_are_kept_but_the_count_goes_on():
    store = ConversationStore(max_turns=2)
    conversation_id, _, _ = store.begin(None)
    store.finish(conversation_id, _turn(1))
    for number in (2, 3):
        store.begin(conversation_id)
        store.finish(conversation_id, _turn(number))
    _, history, turn = store.begin(conversation_id)
    assert history == (_turn(2), _turn(3)) and turn == 4


def test_an_unknown_conversation_is_refused():
    with pytest.raises(UnknownConversation):
        ConversationStore().begin("0" * 32)


def test_the_least_recently_used_idle_conversation_is_forgotten_first():
    store = ConversationStore(max_conversations=2)
    first, _, _ = store.begin(None)
    store.finish(first, None)
    second, _, _ = store.begin(None)
    store.finish(second, None)
    store.begin(first)
    store.finish(first, None)
    store.begin(None)
    assert len(store) == 2
    with pytest.raises(UnknownConversation):
        store.begin(second)
    store.begin(first)


def test_a_conversation_still_answering_is_never_forgotten():
    store = ConversationStore(max_conversations=1)
    busy, _, _ = store.begin(None)
    newer, _, _ = store.begin(None)
    store.finish(busy, _turn(1))
    store.finish(newer, None)
    _, history, _ = store.begin(busy)
    assert history == (_turn(1),)


ANSWER = {"headline": "Eight.", "queries": [{"sql": "SELECT 8", "rows": [[8]]}]}
STEPS = [{"kind": "sql", "detail": "SELECT 8"}]


def _answered(store, conversation_id=None, question="How many have diabetes?", tokens=(1200, 150)):
    conversation_id, _, _ = store.begin(conversation_id)
    store.finish(
        conversation_id,
        Turn(question=question, answer="Eight.", sql=("SELECT 8",)),
        answer=ANSWER,
        steps=STEPS,
        input_tokens=tokens[0],
        output_tokens=tokens[1],
    )
    return conversation_id


def test_a_conversation_survives_a_restart_and_can_be_continued(tmp_path):
    path = tmp_path / "nested" / "conversations.db"
    store = ConversationStore(path)
    conversation_id = _answered(store)
    store.close()

    reopened = ConversationStore(path)
    _, history, turn = reopened.begin(conversation_id)
    assert history == (Turn(question="How many have diabetes?", answer="Eight.", sql=("SELECT 8",)),)
    assert turn == 2


def test_a_stored_conversation_is_returned_as_the_interface_was_sent_it(tmp_path):
    store = ConversationStore(tmp_path / "conversations.db")
    conversation_id = _answered(store)
    stored = store.get(conversation_id)
    assert stored.busy is False and stored.summary.turn_count == 1
    (turn,) = stored.turns
    assert (turn.turn, turn.question, turn.answer, turn.steps) == (1, "How many have diabetes?", ANSWER, STEPS)


def test_every_turn_is_kept_even_though_only_recent_ones_are_replayed():
    store = ConversationStore(max_turns=2)
    conversation_id = _answered(store, question="question 1")
    for number in (2, 3):
        _answered(store, conversation_id, question=f"question {number}")
    assert [turn.question for turn in store.get(conversation_id).turns] == ["question 1", "question 2", "question 3"]
    _, history, _ = store.begin(conversation_id)
    assert [turn.question for turn in history] == ["question 2", "question 3"]


def test_the_title_is_the_first_question_on_one_line_and_cut_short():
    store = ConversationStore()
    short = _answered(store, question="  How many\npatients   have diabetes? ")
    long = _answered(store, question="word " * 40)
    _answered(store, short, question="And heart disease?")
    titles = {summary.id: summary.title for summary in store.list()}
    assert titles[short] == "How many patients have diabetes?", "a later question does not rename it"
    assert len(titles[long]) == 60 and titles[long].endswith("…")


def test_the_list_is_most_recently_used_first_and_leaves_out_unanswered_conversations():
    store = ConversationStore()
    first = _answered(store, question="first")
    second = _answered(store, question="second")
    unanswered, _, _ = store.begin(None)
    store.finish(unanswered, None)
    assert [summary.id for summary in store.list()] == [second, first]
    _answered(store, first, question="again")
    assert [summary.id for summary in store.list()] == [first, second]


def test_a_conversation_can_be_renamed():
    store = ConversationStore()
    conversation_id = _answered(store)
    assert store.rename(conversation_id, "  Diabetes\ncounts ").title == "Diabetes counts"
    assert store.get(conversation_id).summary.title == "Diabetes counts"
    with pytest.raises(ValueError):
        store.rename(conversation_id, "   ")
    with pytest.raises(UnknownConversation):
        store.rename("0" * 32, "x")


def test_deleting_a_conversation_removes_its_turns(tmp_path):
    store = ConversationStore(tmp_path / "conversations.db")
    conversation_id = _answered(store)
    store.delete(conversation_id)
    assert store.list() == []
    assert store._db.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 0
    with pytest.raises(UnknownConversation):
        store.begin(conversation_id)


def test_a_conversation_still_answering_cannot_be_deleted():
    store = ConversationStore()
    conversation_id, _, _ = store.begin(None)
    with pytest.raises(ConversationBusy):
        store.delete(conversation_id)
    assert store.get(conversation_id).busy is True


def test_a_run_that_finishes_after_its_conversation_was_removed_is_dropped():
    store = ConversationStore(max_conversations=1)
    conversation_id = _answered(store)
    store._db.execute("DELETE FROM conversations")
    store.finish(conversation_id, Turn(question="late", answer="late"))
    assert len(store) == 0


def test_the_tokens_a_conversation_spent_are_kept_with_it(tmp_path):
    path = tmp_path / "conversations.db"
    store = ConversationStore(path)
    conversation_id = _answered(store, tokens=(1000, 200))
    _answered(store, conversation_id, tokens=(2000, 300))
    store.close()
    assert ConversationStore(path).tokens_spent(conversation_id) == 3500
    assert ConversationStore().tokens_spent("0" * 32) == 0
