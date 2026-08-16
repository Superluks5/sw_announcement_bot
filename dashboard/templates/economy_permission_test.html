{% extends "base.html" %}
{% block page_title %}🧪 Test Permissions{% endblock %}
{% block content %}
        <p class="hint">Pick a member and a command to see exactly ALLOW/DENY and which rule caused it.</p>

        <form method="POST" class="hud-panel" style="max-width: 480px; display: flex; flex-direction: column; gap: 10px;">
            <label style="font-size: 12px; color: var(--text-dim);">Member</label>
            <select name="member_id" required>
                {% for m in members %}<option value="{{ m.id }}">{{ m.name }}</option>{% endfor %}
            </select>

            <label style="font-size: 12px; color: var(--text-dim);">Command</label>
            <select name="command" required>
                {% for c in commands %}<option value="{{ c }}">/{{ c }}</option>{% endfor %}
            </select>

            <label style="font-size: 12px; color: var(--text-dim);">Channel (optional)</label>
            <select name="channel_id">
                <option value="">-- None --</option>
                {% for c in channels %}<option value="{{ c.id }}">#{{ c.name }}</option>{% endfor %}
            </select>

            <button type="submit">Run Test</button>
        </form>

        {% if result %}
        <div class="hud-panel" style="max-width: 480px; margin-top: 20px; border-color: {{ '#22c55e' if result.allowed else '#dc2626' }};">
            <div style="font-family: 'Rajdhani', sans-serif; font-size: 20px; font-weight: 700; color: {{ '#86efac' if result.allowed else '#fca5a5' }};">
                {{ 'ALLOWED' if result.allowed else 'DENIED' }}
            </div>
            <p style="font-size: 13px; color: var(--text-dim); margin-top: 8px;">{{ result.reason }}</p>
        </div>
        {% endif %}
{% endblock %}
