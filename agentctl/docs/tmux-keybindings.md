# tmux Keybindings for agentctl

Quick access to the agentctl TUI from within agent tmux sessions.

## Recommended Setup: Switch to Dedicated Session

Add this to your `~/.tmux.conf`:

```bash
# Quick switch to agentctl agents monitor session
# Press prefix + g (e.g., Ctrl-b g) to switch to agentctl session
bind-key g switch-client -t agentctl
```

### Setup:
1. Create a dedicated tmux session for agentctl:
   ```bash
   tmux new-session -d -s agentctl "agentctl dash --agents"
   ```

2. Add the keybinding to your `~/.tmux.conf` (shown above)

3. Reload tmux config:
   ```bash
   tmux source-file ~/.tmux.conf
   ```

### How to Use:
1. While attached to an agent's tmux session, press your tmux prefix (default: `Ctrl-b`)
2. Press `g` to switch to the agentctl session
3. Navigate with `j`/`k`, press `enter` to attach to another agent
4. Press `prefix + L` (last session) or `prefix + g` again to switch back

### Why This Works Best:
- **Fast**: Instant switch between sessions
- **Persistent**: The agentctl TUI stays running and maintains state
- **Unused**: `g` is available in default tmux (not bound by default)
- **Direct**: Goes straight to agents list, not the main dashboard

### Auto-start on tmux Launch

To automatically create the agentctl session when tmux starts, add to your shell config (`.bashrc`, `.zshrc`, etc.):

```bash
# Auto-create agentctl session if it doesn't exist
if command -v tmux &> /dev/null && command -v agentctl &> /dev/null; then
    if ! tmux has-session -t agentctl 2>/dev/null; then
        tmux new-session -d -s agentctl "agentctl dash --agents"
    fi
fi
```

## Alternative: Popup Overlay

If you prefer a temporary overlay instead of switching sessions:

```bash
# Open agents monitor as popup overlay
bind-key g popup -E -w 90% -h 90% "agentctl dash --agents"
```

Press `q` to close the popup and return to your session.

## Reload Configuration

After editing `~/.tmux.conf`:

```bash
tmux source-file ~/.tmux.conf
```

Or from within tmux: `prefix + :` then type `source-file ~/.tmux.conf`
