{% if event.description -%}
**Description**

{{ event.description }}
{% endif %}

{% if event.created_by -%}
**Created by**: {{ event.created_by.fetch().name }}
{% endif %}

[Click here to RSVP]({{ url }})
