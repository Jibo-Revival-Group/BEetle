"""Actual Tk widgets; run with JIBO_GUI_TEST_DISPLAY=1 under Xvfb or a desktop."""
import os
import time
from unittest.mock import patch

import pytest
import jibo_gui_core as core
from gui_fakes import FakeApi

pytestmark = pytest.mark.skipif(os.environ.get("JIBO_GUI_TEST_DISPLAY") != "1",
                                reason="opt-in real-window lane requires Tk and a display")


@pytest.fixture
def window():
    import jibo_gui as gui
    root = gui.create_root()
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(exc)
    c = core.GuiController(FakeApi(), runner=core.sync_runner)
    w = gui.ToolkitWindow(root, c)
    root.update()
    yield w
    w.controller._busy = False
    if not w.closed:
        w.close()
    assert not errors, errors


def boot_prompt(w):
    return core.Prompt("select", "Boot screen network status", initial="install",
                       detail="Install/remove uses one full 500 MiB var transaction with mode and Wi-Fi, rollback backup and SHA-256 readback. No services partition is rewritten. Unknown SSM hashes safely keep the stock screen.",
                       prompt="This diagnostic uses only local network status, not the cloud.",
                       items=w.controller.flows._normalise_options((
                           ("install", "Show Wi-Fi status and IP on the boot screen"),
                           ("keep", "Leave the current boot-screen setting unchanged"),
                           ("remove", "Remove the boot-screen Wi-Fi/IP status"))))


def test_boot_network_checkbox_defaults_on_and_off_means_keep(window):
    w = window
    p = boot_prompt(w)
    w.show_prompt(p)
    w.root.update()
    assert w.controls["boot_enabled"].get() is True
    assert w.controls["checkbox"].winfo_ismapped()
    w.controls["checkbox"].invoke()
    w.controls["primary"].invoke()
    assert p.wait() == "keep"


def test_boot_network_checkbox_on_means_install(window):
    p = boot_prompt(window)
    window.show_prompt(p)
    window.controls["primary"].invoke()
    assert p.wait() == "install"


def test_boot_remove_remains_a_separate_explicit_choice(window):
    p = boot_prompt(window)
    window.show_prompt(p)
    window.controls["remove"].invoke()
    assert p.wait() == "remove"


def test_confirm_defaults_cancel_and_cannot_accept_carried_double_click(window):
    import jibo_gui as gui
    p = core.Prompt("confirm", "Confirm var write", detail="Exact review\nUSB port: 1-1",
                    items=window.controller.flows._normalise_options((("cancel", "Cancel"), ("confirm", "Confirm"))),
                    initial="cancel")
    window.show_prompt(p)
    window.root.update()
    assert window.controls["cancel"] == window.root.focus_get()
    assert window.controls["review"].get() == p.detail
    window.controls["primary"].invoke()
    assert not p.answered
    window.controls["cancel"].event_generate("<Return>")
    window.root.update()
    assert p.answered and p.wait() is None


def test_confirm_only_arms_current_live_prompt(window):
    import jibo_gui as gui
    p = core.Prompt("confirm", "Confirm var write", items=window.controller.flows._normalise_options(
        (("cancel", "Cancel"), ("confirm", "Confirm"))))
    window.show_prompt(p)
    window.root.update()
    deadline = time.monotonic() + gui._CONFIRM_ARM_MS / 1000 + 0.2
    while time.monotonic() < deadline:
        window.root.update()
        time.sleep(0.01)
    assert not window.controls["primary"].instate(["disabled"])
    window.controls["primary"].invoke()
    assert p.wait() == "confirm"


def test_multi_selection_supports_keyboard_without_mouse(window):
    p = core.Prompt("multi", "Choose partitions", items=window.controller.flows._normalise_options(
        (("var", "var"), ("services", "services"))), initial=("var",))
    window.show_prompt(p)
    window.root.update()
    window.page.event_generate("<Down>")
    window.page.event_generate("<space>")
    window.root.update()
    assert window.controls["chosen"] == {"var", "services"}


def test_password_entry_is_hidden_and_cleared_on_accept(window):
    p = core.Prompt("text", "Configure Wi-Fi", prompt="Wi-Fi password:", password=True)
    window.show_prompt(p)
    window.root.update()
    variable = window.controls["value"]
    assert window.controls["entry"].cget("show")
    variable.set("fakepass1")
    window.controls["primary"].invoke()
    assert variable.get() == "" and p.wait() == "fakepass1"


def test_close_refuses_to_interrupt_active_transfer(window):
    window.controller._busy = True
    with patch("jibo_gui.messagebox.showwarning") as warn:
        window.close()
    assert warn.call_count == 1 and not window.closed
    window.controller._busy = False


def test_close_cannot_treat_already_approved_prompt_as_cancellable(window):
    window.controller._busy = True
    pending = core.Prompt("confirm", "Confirm var write")
    pending.resolve("confirm")
    window.controller._pending = pending
    with patch("jibo_gui.messagebox.showwarning") as warning, \
            patch("jibo_gui.messagebox.askyesno", return_value=True) as question:
        window.close()
    assert warning.call_count == 1 and not question.called and not window.closed
    window.controller._busy = False


def test_full_var_flow_titles_do_not_claim_quick_edit(window):
    window.controller._active_label = "Set mode and configure Wi-Fi (quick edit)"
    assert "quick edit" not in window._kicker()
    window.show_outcome(core.Outcome("result", "set-mode-wifi",
                       "Set mode and configure Wi-Fi (quick edit)", ("Done",), "verified"))
    text = [str(widget.cget("text")) for widget in window.page.winfo_children()
            if "text" in widget.keys()]
    assert not any("quick edit" in value for value in text)


def test_close_prompt_defaults_no_and_does_not_quit_on_refusal(window):
    window.controller._busy = True
    window.controller._pending = core.Prompt("text", "Wi-Fi")
    with patch("jibo_gui.messagebox.askyesno", return_value=False) as question:
        window.close()
    assert question.call_args.kwargs["default"] == "no"
    assert not window.closed
    window.controller._busy = False


def test_progress_displays_numeric_percentage_and_operation_log(window):
    window.controller.write_output("Reading var\n\r[########------------] 40.0% | 200/500 MiB")
    window.show_progress()
    window.root.update()
    assert float(window.progress_bar.cget("value")) == 40
    assert window.progress_step.cget("text") == "Reading var"
    assert "200/500 MiB" in window.progress_status.cget("text")
    assert window.progress_log.get() == "Reading var"


def test_error_result_is_visibly_failed(window):
    window.show_outcome(core.Outcome("error", "write-var", "Action failed", ("Fake readback mismatch",)))
    window.root.update()
    assert window.page_name == "result" and window.controls["tone"] == "danger"
