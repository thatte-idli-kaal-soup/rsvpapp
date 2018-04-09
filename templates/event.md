*{{TEXT2}}*

{% for item in items -%}
    {{loop.index}}. {{ item.name }}
{% endfor %}

{% if not event.archived -%}
    Call in here: {{request.url}}
{% endif %}
