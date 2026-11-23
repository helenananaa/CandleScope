"""Publish a status through the unified backend context."""


def activate(context):
    context.publish({"runtime": "python-host", "mode": "terminal"})
