{% autoescape true %}
*{{TEXT2}}*

{% for rsvp in active_rsvps -%}
    {% set user = rsvp.user.fetch() -%}
    {% if not rsvp.cancelled -%}
        {{loop.index}}. {% if user.is_anonymous_user %}{{rsvp.note}}{% else %}{{ user.name }}{% endif %}
    {%- endif %}
{% endfor %}

{% endautoescape %}
