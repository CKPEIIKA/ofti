from ofti.core import events, messages


def test_events_helpers() -> None:
    nav = events.navigate("menu:root")
    assert nav.name == "navigate"
    assert nav.payload == {"target": "menu:root"}

    note = events.notify("hello")
    assert note.name == "notify"
    assert note.payload == {"message": "hello"}


def test_messages_helpers() -> None:
    info = messages.info("ok")
    warn = messages.warn("careful")
    err = messages.error("boom")

    assert info.level == "info"
    assert warn.level == "warn"
    assert err.level == "error"
