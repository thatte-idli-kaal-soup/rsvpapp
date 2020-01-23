{% autoescape true %}
*{{TEXT2}}*

{% for rsvp in active_rsvps -%}
    {% set user = rsvp.user.fetch() -%}
    {% if not rsvp.cancelled -%}
        {{loop.index}}. {% if user.is_anonymous_user %}{{ rsvp.note }}{% else %}{{ user.nick or user.name }}{% if rsvp.note %} ({{ rsvp.note }}){% endif %}{% endif %}
    {%- endif %}
{% endfor %}

{% if not event.archived -%}
    RSVP here: {{request.base_url}}?attending=yes
{% endif %}
{% endautoescape %}
