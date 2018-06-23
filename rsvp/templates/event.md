*{{TEXT2}}*

{% if event.description -%}
    {{event.description}}
{% endif %}

{% for item in items -%}
    {% set user = item.user.fetch() -%}
    {{loop.index}}. {{ user.nick or user.name }}{% if item.note %} ({{ item.note }}){% endif %}
{% endfor %}

{% if not event.archived -%}
    RSVP here: {{request.url}}
{% endif %}
