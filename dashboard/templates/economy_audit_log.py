{% extends "base.html" %}
{% block page_title %}📜 Economy Audit Log{% endblock %}
{% block content %}
        <p class="hint">Every economy-admin action and permission change, most recent first.</p>

        {% if logs %}
        <div style="max-height: 75vh; overflow-y: auto;">
        {% for log in logs %}
        <div style="background: var(--panel); border-left: 3px solid var(--border-bright); border-radius: 4px; padding: 10px 14px; margin-bottom: 6px; font-size: 12.5px;">
            <div style="color: var(--text-faint); font-size: 11px; margin-bottom: 4px;">
                {{ log.timestamp.strftime('%b %d, %H:%M:%S') }} · <@{{ log.admin_id }}> · {{ log.action }}
            </div>
            <div style="color: var(--text);">{{ log.details or '-' }}</div>
        </div>
        {% endfor %}
        </div>
        {% else %}
        <p class="hint">No audit log entries yet.</p>
        {% endif %}
{% endblock %}
