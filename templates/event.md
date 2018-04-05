*{{TEXT2}}*

{% for item in items -%}
    {{loop.index}}. {{ item.name }}
{% endfor %}
Call in here: {{request.url}}
