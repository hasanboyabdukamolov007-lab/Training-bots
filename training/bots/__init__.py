"""Executable Telegram runtimes for the three training manager bots.

Each bot is a real Telegram bot that a trainee talks to: it polls `getUpdates`,
answers commands, and walks the trainee through one assigned scenario from
`training.scenarios`.

They are tutors, not simulated colleagues. Telegram bots cannot see each other's
group messages, so three bots cannot model a team interacting — see AUDIT.md §3.
What they can do is each teach one scenario, which is what they do.

Sends are suppressed unless `TRAINING_DRY_RUN=false` is set explicitly.
"""

__all__ = ["config", "log", "api", "lock", "manager", "supervisor"]
