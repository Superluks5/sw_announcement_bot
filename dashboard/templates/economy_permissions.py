{% extends "base.html" %}
{% block page_title %}🔐 Economy Permissions{% endblock %}
{% block content %}
        <div class="warn" style="margin-bottom: 20px;">
            ⚠️ Discord Administrators get <strong>no automatic access</strong> to economy admin commands here -
            this is a separate permission system from the rest of the bot. Access must be explicitly granted below.
        </div>

        <h3 style="font-family: 'Rajdhani', sans-serif; font-size: 15px; margin: 0 0 10px;">Presets</h3>
        <p class="hint">Apply a bundle of permissions to a Discord role in one click.</p>
        <form method="POST" action="{{ url_for('economy_apply_preset') }}" style="display: flex; gap: 8px; margin-bottom: 24px; flex-wrap: wrap;">
            <select name="role_id" required>
                {% for r in roles %}<option value="{{ r.id }}">{{ r.name }}</option>{% endfor %}
            </select>
            <select name="preset_name" required>
                {% for p in preset_names %}<option value="{{ p }}">{{ p }}</option>{% endfor %}
            </select>
            <button type="submit">Apply Preset</button>
        </form>

        {% if role_presets %}
        <div style="margin-bottom: 24px;">
            {% for role_id, preset in role_presets.items() %}
            <span class="status-pill" style="margin-right: 6px; margin-bottom: 6px;">{{ role_names.get(role_id|string, role_id) }} → {{ preset }}</span>
            {% endfor %}
        </div>
        {% endif %}

        <h3 style="font-family: 'Rajdhani', sans-serif; font-size: 15px; margin: 20px 0 10px;">Add a Custom Rule</h3>
        <form method="POST" action="{{ url_for('economy_add_rule') }}" style="display: flex; gap: 8px; margin-bottom: 24px; flex-wrap: wrap; align-items: center;">
            <select name="target_type" required>
                <option value="user">User</option>
                <option value="role">Role</option>
                <option value="channel">Channel</option>
            </select>
            <select name="target_id" required style="min-width: 160px;">
                {% for m in members %}<option value="{{ m.id }}">👤 {{ m.name }}</option>{% endfor %}
                {% for r in roles %}<option value="{{ r.id }}">🎭 {{ r.name }}</option>{% endfor %}
                {% for c in channels %}<option value="{{ c.id }}">#️⃣ {{ c.name }}</option>{% endfor %}
            </select>
            <select name="rule_type" required>
                <option value="command">Specific command</option>
                <option value="category">Whole category (e.g. "economy")</option>
            </select>
            <input type="text" name="command_or_category" placeholder="e.g. economy give, or economy, or *" required style="min-width: 180px;">
            <select name="effect" required>
                <option value="allow">ALLOW</option>
                <option value="deny">DENY</option>
            </select>
            <button type="submit">Add Rule</button>
        </form>
        <p class="hint">Tip: target_id dropdown lists users, then roles, then channels in that order - pick the one matching your target type selection.</p>

        <h3 style="font-family: 'Rajdhani', sans-serif; font-size: 15px; margin: 20px 0 10px;">Current Rules</h3>
        <table>
            <thead>
                <tr>
                    <th>Target</th><th>Type</th><th>Rule</th><th>Effect</th><th></th>
                </tr>
            </thead>
            <tbody>
                {% for row in rule_rows %}
                <tr>
                    <td>{{ row.rule.target_type }}: {{ row.target_label }}</td>
                    <td>{{ row.rule.rule_type }}</td>
                    <td style="font-family: monospace;">{{ row.rule.command_or_category }}</td>
                    <td style="color: {{ '#86efac' if row.rule.effect == 'allow' else '#fca5a5' }};">{{ row.rule.effect|upper }}</td>
                    <td>
                        <form method="POST" action="{{ url_for('economy_remove_rule', rule_id=row.rule.id) }}" onsubmit="return confirm('Remove this rule?');">
                            <button type="submit" class="btn-small" style="background: var(--red-dim);">Remove</button>
                        </form>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="5" style="color: var(--text-faint);"><em>No custom rules yet - only presets applied above are active.</em></td></tr>
                {% endfor %}
            </tbody>
        </table>

        <div style="margin-top: 20px; display: flex; gap: 10px;">
            <a href="{{ url_for('economy_permission_test_page') }}" class="btn btn-secondary">🧪 Test Permissions</a>
            <a href="{{ url_for('economy_audit_log_page') }}" class="btn btn-secondary">📜 Audit Log</a>
        </div>
{% endblock %}
