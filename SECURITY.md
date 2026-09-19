# Security Policy

## Trust model

This project is open source. The bot commands, permission checks, dashboard
routes, and approval logic are intentionally visible so server owners can
review them. There is no hidden administrator command or private code path that
gives the maintainer access to a server.

The official hosted instance is identified by its Discord application, bot
account, repository, and published release history. A fork can run its own
instance with its own Discord application and token, but it must not use the
official name, logo, or identity to impersonate the official bot.

`DASHBOARD_ALLOWED_USER_IDS` and `SUPER_ADMIN_USER_IDS` protect the dashboard
for the operator of a particular deployment. They do not grant the maintainer
access to Discord servers using another deployment. Discord server permissions
and the visible code control bot command access.

## Keep private

Never commit or publish:

- `.env` files
- Discord bot tokens or OAuth client secrets
- Groq or other API keys
- dashboard session secrets and passwords
- `economy/economy.db` and runtime `*_data.json` files
- production logs, webhooks, or server-specific role IDs

Use `.env.example` as the public configuration template. The live `.env` file
is ignored by Git, but verify `git status` before every push.

## Reporting a vulnerability

Please report security issues privately to the project maintainer before
publishing them. Include the affected file, a clear reproduction, impact, and
any suggested fix. Do not include live tokens or personal data in a report.

Rotate any credential that may have appeared in an issue, log, screenshot, or
chat immediately, then investigate recent use of that credential.

## Releases and review

Changes that affect permissions, authentication, OAuth, server approval, or
Discord API access should be reviewed publicly and included in release notes.
Operators should inspect the requested Discord permissions before installing a
release.
