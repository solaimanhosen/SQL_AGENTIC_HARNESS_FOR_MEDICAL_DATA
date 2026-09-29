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
