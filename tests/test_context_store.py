from elifelse.providers.base import ContextStore


def make_store(max_chars=1000, agent_name="Agent"):
    return ContextStore(max_chars=max_chars, agent_name=agent_name)


def test_add_appends_timestamp_and_parallel_iso():
    s = make_store()
    s.add("user", "hello")
    assert len(s.messages) == 1
    assert len(s.timestamps) == 1
    content = s.messages[0]["content"]
    assert content.startswith("hello\n[")
    # ISO timestamp parseable
    from datetime import datetime

    datetime.fromisoformat(s.timestamps[0])


def test_system_messages_never_stored():
    s = make_store()
    s.add("system", "sneaky")
    assert len(s.messages) == 0


def test_assistant_gets_name():
    s = make_store()
    s.add("assistant", "hi")
    assert s.messages[0]["name"] == "Agent"


def test_build_messages_system_prompt_first_and_current():
    s = make_store()
    s.set_system_prompt("prompt A")
    s.add("user", "one")
    s.set_system_prompt("prompt B")
    msgs = s.build_messages()
    assert msgs[0] == {"role": "system", "content": "prompt B"}
    assert len(msgs) == 2


def test_trim_from_front_keeps_min_two():
    s = make_store(max_chars=50)
    for i in range(10):
        s.add("user", f"message number {i} padding padding")
    assert len(s.messages) == 2  # min 2 kept even over budget
    assert "number 8" in s.messages[0]["content"]
    assert len(s.timestamps) == len(s.messages)


def test_system_prompt_never_trimmed():
    s = make_store(max_chars=10)
    s.set_system_prompt("X" * 500)
    s.add("user", "a")
    s.add("user", "b")
    s.add("user", "c")
    assert s.system_prompt == "X" * 500
    assert len(s.messages) == 2


def test_snapshot_restore_byte_identical():
    s = make_store()
    s.set_system_prompt("base")
    s.add("user", "one")
    s.add("assistant", "two")
    snap = s.snapshot()
    before = [dict(m) for m in s.messages]
    before_ts = list(s.timestamps)

    s.add("user", "activity msg")
    s.set_system_prompt("activity prompt")
    s.clear()
    s.restore(snap)

    assert [dict(m) for m in s.messages] == before
    assert list(s.timestamps) == before_ts
    assert s.system_prompt == "base"


def test_messages_since_snapshot():
    s = make_store()
    s.add("user", "before")
    snap = s.snapshot()
    s.add("user", "during 1")
    s.add("assistant", "during 2")
    new = s.messages_since(snap)
    assert len(new) == 2
    assert "during 1" in new[0]["content"]


def test_oldest_timestamp():
    s = make_store()
    assert s.oldest_timestamp() is None
    s.add("user", "x")
    assert s.oldest_timestamp() == s.timestamps[0]


def test_image_placeholder():
    s = make_store()
    s.add("user", "look at this", image_placeholder=True)
    assert "(image)" in s.messages[0]["content"]
