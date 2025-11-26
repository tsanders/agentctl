# tmux Keybindings for agentctl

Quick access to the agentctl TUI from within agent tmux sessions.

## Recommended Setup: Popup Overlay

Add this to your `~/.tmux.conf`:

```bash
# Quick access to agentctl agents monitor
# Press prefix + g (e.g., Ctrl-b g) to open agents list as popup
bind-key g popup -E -w 90% -h 90% "agentctl dash --agents"
```

### Why This Works Best:
- **Fast**: Opens instantly as an overlay
- **Non-destructive**: Doesn't detach or lose your place in the agent session
- **Unused**: `g` is available in default tmux (not bound by default)
- **Direct**: Goes straight to agents list, not the main dashboard

### How to Use:
1. While attached to an agent's tmux session, press your tmux prefix (default: `Ctrl-b`)
2. Press `g`
3. The agents monitor opens as a popup overlay
4. Use `j`/`k` to navigate, press `enter` to switch to another agent
5. Press `q` to close the popup and return to your session

## Alternative: Detach and Launch

If you prefer to detach from the agent session:

```bash
# Detach and launch agents monitor
bind-key g detach-client \; run-shell "agentctl dash --agents"
```

## Alternative: Quick Toggle Between Sessions

If you run agentctl in its own tmux session:

```bash
# Toggle between current session and agentctl session
bind-key g switch-client -t agentctl
```

## Reload Configuration

After editing `~/.tmux.conf`:

```bash
tmux source-file ~/.tmux.conf
```

Or from within tmux: `prefix + :` then type `source-file ~/.tmux.conf`
