"""Contract fixture, not evidence of service replacement or production loading."""


def activate(context):
    context.track(lambda: None)
