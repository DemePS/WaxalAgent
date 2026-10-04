"""Finding the right model id in Soynade's model list when it is not set in the environment."""

from .soynade_api import SoynadeClient, SoynadeError

# What each job's model id is expected to contain, and not to contain (a guess from the names: set the variable to be sure).
KINDS = {
    "translation": (("oolel",), ("speech", "voice", "tts", "audio", "asr")),
    "speech output": (("voice", "tts"), ()),
}


def pick(client: SoynadeClient, kind: str, variable: str) -> str:
    """The model id for `kind` from the list; an error that shows the list when none (or several) fit."""
    models = client.models()
    want, avoid = KINDS[kind]
    found = [m for m in models if any(w in m.lower() for w in want) and not any(a in m.lower() for a in avoid)]
    if len(found) == 1:
        return found[0]
    if not found and len(models) == 1:  # a single multimodal model (e.g. oolel-speech-v1) does everything: use it
        return models[0]
    reason = "none fits" if not found else f"several fit ({', '.join(found)})"
    raise SoynadeError(f"Which Soynade model is for {kind}? {reason}. Models available to your key: "
                       f"{', '.join(models) or '(none)'}. Set {variable} to the right id.")
