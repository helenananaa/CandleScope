"""A host entry with owned cleanup; architecture factory takeover is a later phase."""


def activate(context):
    previous = getattr(context.app.state, "unified_workbench", None)
    value = {
        "plugin": context.id,
        "entry": context.entry_id,
        "generation": context.identity.generation,
    }
    context.app.state.unified_workbench = value

    def restore():
        if getattr(context.app.state, "unified_workbench", None) is value:
            context.app.state.unified_workbench = previous

    context.track(restore)


def invoke(context, payload):
    return {"identity": context.identity.to_wire(), "input": payload}


def compute_chart(context, request):
    context.ensure_current()
    return {"points": [
        {"timeMs": bar["openTimeMs"], "value": bar["close"]}
        for bar in request["bars"]
    ]}
