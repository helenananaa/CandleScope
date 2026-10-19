"""A harmless example of an in-process service with automatic restoration."""


def activate(context):
    context.replace_service("terminal_extension_status", {
        "id": context.extension_id,
        "api": context.api_version,
        "runtime": "python-host",
    })
