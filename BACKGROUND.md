Context and Background
- I am using multiple AI coding agents to work on multiple application projects at once. Some are API backends, web frontends, and native mobile frontends.  Some are working on features, bugs, etc.
- I run these agents using a variety of Claude Code, ChatGPT Codex, and Cursor Agent CLI tools.
- Each agent CLI session runs inside its own tmux session. I will open additional tmux session windows within one session so that I can use human tools such as ranger, lazygit, nvim, to review code, modify configuration, and run other ad hoc commands such as test suite runs.
- I typically write out a "TASK" file in Obsidian with frontmatter metadata such as the task title, status, completion percentage, priority, category, type, etc.
	- The tasks follow the format - [PROJECT_CODE]-[CATEGORY]-[NNNN]
	- For example: `RRA-API-0082`, `RRA-BUG-0103`, `RRA-WEB-0290`

## Goals
- I want to keep the agents running continuously with minimal supervision
- Maintain the highest quality of work to avoid manually troubleshooting bugs
- Increase parallelism, handle more agents do more work in parallel
- I need a better way to track and visualize the progress and validation of an agent's current, pass, and future tasks.

## Task
- Evaluate my process - where may I improve? How can I better manage the agents to minimize context switching and maximize the potential of the AI coding agents.
- What better workflows and ideas do you have?  I am open to fully changing my workflows described here.
