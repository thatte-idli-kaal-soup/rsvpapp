*{{TEXT2}}*

{% for rsvp in active_rsvps -%}
    {% set user = rsvp.user.fetch() -%}
    {% if not rsvp.cancelled -%}
        {{loop.index}}. {{ user.nick or user.name }}{% if rsvp.note %} ({{ rsvp.note }}){% endif %}
    {%- endif %}
{% endfor %}

{% if not event.archived -%}
    RSVP here: {{request.url}}
{% endif %}
