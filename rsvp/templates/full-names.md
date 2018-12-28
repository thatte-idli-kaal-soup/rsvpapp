{% autoescape true %}
*{{TEXT2}}*

{% for rsvp in active_rsvps -%}
    {% set user = rsvp.user.fetch() -%}
    {% if not rsvp.cancelled -%}
        {{loop.index}}. {{ user.name }}
    {%- endif %}
{% endfor %}

{% endautoescape %}
