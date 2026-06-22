from models.design_spec import DesignSpec
from google import genai
from google.genai import types


# Plain def — the Google GenAI SDK is synchronous.
# Called via asyncio.to_thread() in the router so it doesn't block the event loop.
def generate_background(client: genai.Client, spec: DesignSpec) -> bytes:
    """Returns raw PNG bytes of the AI-generated background scene."""
    prompt = (
        f"{spec.background_prompt}. "
        "No text overlays. No logos. No watermarks. "
        "Cinematic lighting, commercial photography aesthetic, "
        f"{spec.canvas_w}x{spec.canvas_h} aspect ratio."
    )

    resp = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )

    for part in resp.candidates[0].content.parts:
        if getattr(part, "thought", False):
            continue
        if part.inline_data:
            return part.inline_data.data

    raise RuntimeError("No image returned from background generation — prompt may have been blocked.")