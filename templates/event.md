*{{TEXT2}}*

{% for item in items -%}
    {{loop.index}}. {{ item.name }}{% if item.note %} ({{ item.note }}){% endif %}
{% endfor %}

{% if not event.archived -%}
    RSVP here: {{request.url}}
{% endif %}
