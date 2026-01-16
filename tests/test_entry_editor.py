from of_tui.editor import Entry, EntryEditor


class FakeScreen:
    def __init__(self, keys):
        # sequence of key codes to return from getch()
        self._keys = list(keys)
        self.lines = []
        self.height = 24
        self.width = 80

    def clear(self):
        self.lines.clear()

    def erase(self):
        self.lines.clear()

    def getmaxyx(self):
        return (self.height, self.width)

    def addstr(self, *args):
        # Support both addstr(text) and addstr(y, x, text)
        text = args[-1]
        self.lines.append(str(text))

    def move(self, y, x):
        # Cursor movement is ignored in tests.
        pass

    def refresh(self):
        pass

    def getch(self):
        if self._keys:
            return self._keys.pop(0)
        # Default to 'q' if keys exhausted to avoid infinite loops.
        return ord("q")


def test_entry_editor_saves_on_enter_with_valid_value():
    entry = Entry(key="testKey", value="0")
    saved = {"value": None}

    def on_save(new_value: str) -> bool:
        saved["value"] = new_value
        return True

    # Sequence: Enter to save, then any key to dismiss success message.
    screen = FakeScreen(keys=[10, ord("x")])

    editor = EntryEditor(
        screen,
        entry,
        on_save,
        validator=lambda v: None,
        type_label="int",
        subkeys=[],
    )
    # Simulate that the user has changed the value before pressing Enter.
    editor._buffer = "1"

    editor.edit()

    assert saved["value"] == "1"


def test_entry_editor_enter_without_change_does_not_save_or_validate():
    entry = Entry(key="testKey", value="unchanged")
    saved = {"value": None}
    validated = {"called": False}

    def on_save(new_value: str) -> bool:
        saved["value"] = new_value
        return True

    def validator(v: str):
        validated["called"] = True
        return "should not be used"

    # Press Enter once; since buffer == original, editor should exit
    # without calling validator or on_save.
    screen = FakeScreen(keys=[10])

    editor = EntryEditor(
        screen,
        entry,
        on_save,
        validator=validator,
        type_label="text",
        subkeys=[],
    )

    editor.edit()

    assert saved["value"] is None
    assert validated["called"] is False


def test_entry_editor_confirms_on_invalid_and_saves_on_yes():
    entry = Entry(key="testKey", value="bad")
    saved = {"value": None}

    def on_save(new_value: str) -> bool:
        saved["value"] = new_value
        return True

    # Keys:
    #  - Enter (attempt save)
    #  - 'y' (confirm dangerous)
    #  - 'x' (dismiss success message)
    screen = FakeScreen(keys=[10, ord("y"), ord("x")])

    # Validator always reports an error.
    def validator(v: str):
        return "example validation error"

    editor = EntryEditor(
        screen,
        entry,
        on_save,
        validator=validator,
        type_label="text",
        subkeys=[],
    )
    # Simulate user changed the value so it is considered a new proposal.
    editor._buffer = "bad-new"

    editor.edit()

    assert saved["value"] == "bad-new"
