"""TUI components for agentctl."""

from textual.app import App

# Import from the main tui module (tui.py in parent directory)
# Note: tui.py is at agentctl/tui.py, this package is at agentctl/tui/__init__.py
# To avoid circular import, we import the run_dashboard at module level would
# require importing from a sibling. Instead, define a wrapper that imports lazily.


def run_dashboard(open_agents: bool = False):
    """Run the dashboard application.

    Args:
        open_agents: If True, open directly to tasks screen with active agents filter
    """
    # Lazy import to avoid circular import with the main tui.py module
    import importlib.util
    import os

    # Load the tui.py file directly (not the package)
    tui_py_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tui.py")
    if os.path.exists(tui_py_path):
        spec = importlib.util.spec_from_file_location("tui_main", tui_py_path)
        tui_main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tui_main)
        tui_main.run_dashboard(open_agents=open_agents)
    else:
        raise ImportError(f"Could not find tui.py at {tui_py_path}")


def run_watch():
    """Run the multi-agent watch screen for monitoring many agents at once."""
    from agentctl.tui.watch_screen import WatchScreen

    class WatchApp(App):
        """Minimal app to host the WatchScreen."""

        BINDINGS = [
            ("q", "quit", "Quit"),
        ]

        def on_mount(self) -> None:
            self.push_screen(WatchScreen())

    app = WatchApp()
    app.run()
