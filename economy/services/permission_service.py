"""
Economy permission engine.
------------------------------------------
Deliberately separate from the bot's existing /permissions.py (which
bypasses everything for Discord Administrators). This engine NEVER checks
guild_permissions.administrator - that's the entire point of this project's
core security requirement. Access to economy-admin commands must be
explicitly granted, either directly or via a preset applied to a role.

Resolution priority (first matching tier wins):
  1. User rule       (explicit allow/deny for this specific person)
  2. Role rule        (across all their roles - DENY wins on conflict)
  3. Channel rule
  4. Channel-category rule
  5. Server default   (admin-tier commands: DENY. Member-tier commands: ALLOW)

Everything here takes plain primitives (ints, strings) rather than a real
discord.Member/Interaction, specifically so it's fully unit-testable without
mocking discord.py. See is_allowed_for_interaction() at the bottom for the
thin adapter used by actual Discord commands.
"""

from dataclasses import dataclass

from economy.db import SessionLocal
from economy.models import PermissionRule, RolePresetAssignment, AuditLog

# Commands in this set default to DENY unless a rule explicitly grants
# access - this is the money-generation/administration surface.
ECONOMY_ADMIN_COMMANDS = {
    "economy give",
    "economy remove",
    "economy set",
    "economy reset",
    "economy reset-server",
}

# Preset name -> list of commands/categories it grants. "*" means every
# economy command/category. Shop Manager and Event Manager reference
# commands that don't exist until later phases - applying them now is
# harmless and just means those rules sit unused until then.
PRESETS: dict[str, list[str]] = {
    "Economy Owner": ["*"],
    "Economy Manager": [
        "economy give", "economy remove", "economy set", "economy reset", "economy reset-server",
    ],
    "Shop Manager": ["shop", "item"],
    "Event Manager": ["role-income", "daily-config", "weekly-config"],
}


@dataclass
class PermissionResult:
    allowed: bool
    reason: str
    matched_rule: PermissionRule | None = None


def _rule_matches(rule: PermissionRule, command: str) -> bool:
    if rule.command_or_category == "*":
        return True
    if rule.rule_type == "command":
        return rule.command_or_category == command
    if rule.rule_type == "category":
        return command.split(" ")[0] == rule.command_or_category
    return False


def check_permission(
    guild_id: int,
    user_id: int,
    role_ids: list[int],
    command: str,
    channel_id: int | None = None,
    channel_category_id: int | None = None,
) -> PermissionResult:
    """The core resolver. Never looks at Discord permissions - only at rows
    in permission_rules. Safe to call for ANY command (not just economy
    ones); commands not in ECONOMY_ADMIN_COMMANDS default to ALLOW when no
    rule matches."""
    with SessionLocal() as session:
        rules = session.query(PermissionRule).filter_by(guild_id=guild_id).all()

    # Tier 1: user rules
    user_rules = [r for r in rules if r.target_type == "user" and r.target_id == user_id and _rule_matches(r, command)]
    if user_rules:
        deny = next((r for r in user_rules if r.effect == "deny"), None)
        chosen = deny or user_rules[0]
        return PermissionResult(
            allowed=(chosen.effect == "allow"),
            reason=f"Explicit user rule ({chosen.effect}) for '{chosen.command_or_category}'",
            matched_rule=chosen,
        )

    # Tier 2: role rules - deny wins on conflict across the user's roles
    role_rules = [r for r in rules if r.target_type == "role" and r.target_id in role_ids and _rule_matches(r, command)]
    if role_rules:
        deny = next((r for r in role_rules if r.effect == "deny"), None)
        chosen = deny or role_rules[0]
        return PermissionResult(
            allowed=(chosen.effect == "allow"),
            reason=f"Role rule ({chosen.effect}) via <@&{chosen.target_id}> for '{chosen.command_or_category}'"
            + (" - deny took priority over a conflicting allow from another role" if deny and len(role_rules) > 1 else ""),
            matched_rule=chosen,
        )

    # Tier 3: channel rules
    if channel_id is not None:
        channel_rules = [r for r in rules if r.target_type == "channel" and r.target_id == channel_id and _rule_matches(r, command)]
        if channel_rules:
            deny = next((r for r in channel_rules if r.effect == "deny"), None)
            chosen = deny or channel_rules[0]
            return PermissionResult(
                allowed=(chosen.effect == "allow"),
                reason=f"Channel rule ({chosen.effect}) for '{chosen.command_or_category}'",
                matched_rule=chosen,
            )

    # Tier 4: channel category rules
    if channel_category_id is not None:
        cat_rules = [r for r in rules if r.target_type == "channel_category" and r.target_id == channel_category_id and _rule_matches(r, command)]
        if cat_rules:
            deny = next((r for r in cat_rules if r.effect == "deny"), None)
            chosen = deny or cat_rules[0]
            return PermissionResult(
                allowed=(chosen.effect == "allow"),
                reason=f"Channel category rule ({chosen.effect}) for '{chosen.command_or_category}'",
                matched_rule=chosen,
            )

    # Tier 5: server default
    if command in ECONOMY_ADMIN_COMMANDS:
        return PermissionResult(
            allowed=False,
            reason="No matching rule found - economy admin commands default to DENY until explicitly granted.",
        )
    return PermissionResult(allowed=True, reason="No matching rule found - default access for a member-tier command.")


def is_allowed_for_interaction(interaction, command: str) -> PermissionResult:
    """Thin adapter for real Discord commands - extracts primitives from a
    discord.Interaction and calls check_permission(). Deliberately does NOT
    check interaction.user.guild_permissions.administrator."""
    member = interaction.user
    role_ids = [r.id for r in getattr(member, "roles", [])]
    channel = interaction.channel
    channel_id = channel.id if channel else None
    category_id = getattr(getattr(channel, "category", None), "id", None)
    return check_permission(interaction.guild_id, member.id, role_ids, command, channel_id, category_id)


# ---------- rule management ----------

def add_rule(guild_id: int, rule_type: str, target_type: str, target_id: int, command_or_category: str, effect: str, created_by: int) -> PermissionRule:
    with SessionLocal() as session:
        rule = PermissionRule(
            guild_id=guild_id, rule_type=rule_type, target_type=target_type, target_id=target_id,
            command_or_category=command_or_category, effect=effect, created_by=created_by,
        )
        session.add(rule)
        session.commit()
        session.refresh(rule)
        record_audit(guild_id, created_by, "permission_rule_added", target_id,
                      f"{effect.upper()} {command_or_category} for {target_type} {target_id}")
        return rule


def remove_rule(guild_id: int, rule_id: int, removed_by: int) -> bool:
    with SessionLocal() as session:
        rule = session.query(PermissionRule).filter_by(id=rule_id, guild_id=guild_id).one_or_none()
        if rule is None:
            return False
        details = f"{rule.effect.upper()} {rule.command_or_category} for {rule.target_type} {rule.target_id}"
        session.delete(rule)
        session.commit()
    record_audit(guild_id, removed_by, "permission_rule_removed", None, details)
    return True


def list_rules(guild_id: int) -> list[PermissionRule]:
    with SessionLocal() as session:
        return session.query(PermissionRule).filter_by(guild_id=guild_id).order_by(PermissionRule.created_at.desc()).all()


def apply_preset(guild_id: int, role_id: int, preset_name: str, applied_by: int):
    if preset_name not in PRESETS:
        raise ValueError(f"Unknown preset: {preset_name}")

    with SessionLocal() as session:
        # Remove this role's previous rules for this preset's commands before reapplying,
        # so switching a role from one preset to another doesn't leave stale grants behind.
        session.query(PermissionRule).filter_by(guild_id=guild_id, target_type="role", target_id=role_id).delete()

        for item in PRESETS[preset_name]:
            if item == "*" or " " not in item:
                rule_type = "category"
            else:
                rule_type = "command"
            session.add(PermissionRule(
                guild_id=guild_id, rule_type=rule_type, target_type="role", target_id=role_id,
                command_or_category=item, effect="allow", created_by=applied_by,
            ))

        existing = session.query(RolePresetAssignment).filter_by(guild_id=guild_id, role_id=role_id).one_or_none()
        if existing:
            existing.preset_name = preset_name
        else:
            session.add(RolePresetAssignment(guild_id=guild_id, role_id=role_id, preset_name=preset_name))

        session.commit()

    record_audit(guild_id, applied_by, "preset_applied", role_id, f"Applied preset '{preset_name}' to role {role_id}")


def get_role_presets(guild_id: int) -> dict[int, str]:
    """role_id -> preset_name, for display in the dashboard."""
    with SessionLocal() as session:
        rows = session.query(RolePresetAssignment).filter_by(guild_id=guild_id).all()
        return {r.role_id: r.preset_name for r in rows}


# ---------- audit log ----------

def record_audit(guild_id: int, admin_id: int, action: str, target_id: int | None = None, details: str | None = None):
    with SessionLocal() as session:
        session.add(AuditLog(guild_id=guild_id, admin_id=admin_id, action=action, target_id=target_id, details=details))
        session.commit()


def get_audit_log(guild_id: int, limit: int = 100) -> list[AuditLog]:
    with SessionLocal() as session:
        return session.query(AuditLog).filter_by(guild_id=guild_id).order_by(AuditLog.timestamp.desc()).limit(limit).all()
