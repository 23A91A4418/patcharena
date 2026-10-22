"""LLM provider wrapper supporting Gemini, Anthropic, and OpenAI."""

from __future__ import annotations

import json
import re

from .config import LLM_API_KEY, LLM_MODEL, LLM_PROVIDER, redact


async def json_call(prompt: str, image_path: str | None = None) -> dict:
    """Call the configured LLM and parse JSON from the response."""
    raw = await _call(prompt, image_path)
    return _parse_json(raw)


async def text_call(prompt: str) -> str:
    """Call the configured LLM and return raw text."""
    return await _call(prompt)


async def _call(prompt: str, image_path: str | None = None) -> str:
    if LLM_PROVIDER == "gemini":
        return await _gemini(prompt, image_path)
    elif LLM_PROVIDER == "anthropic":
        return await _anthropic(prompt, image_path)
    elif LLM_PROVIDER == "openai":
        return await _openai(prompt, image_path)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")


def _parse_json(text: str) -> dict:
    """Extract JSON from LLM response (handles markdown code blocks)."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from ```json ... ``` block
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Try finding first { ... } block
    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")


async def _gemini(prompt: str, image_path: str | None = None) -> str:
    import asyncio
    import google.generativeai as genai
    genai.configure(api_key=LLM_API_KEY)
    model = genai.GenerativeModel(LLM_MODEL)

    parts = [prompt]
    if image_path:
        import PIL.Image
        img = PIL.Image.open(image_path)
        parts.append(img)

    response = await asyncio.to_thread(model.generate_content, parts)
    return response.text


async def _anthropic(prompt: str, image_path: str | None = None) -> str:
    import asyncio
    import base64
    import anthropic

    client = anthropic.Anthropic(api_key=LLM_API_KEY)
    content: list = []

    if image_path:
        with open(image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": img_data}
        })

    content.append({"type": "text", "text": prompt})

    def _sync_call():
        return client.messages.create(
            model=LLM_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": content}]
        )

    msg = await asyncio.to_thread(_sync_call)
    return msg.content[0].text


async def _openai(prompt: str, image_path: str | None = None) -> str:
    from openai import AsyncOpenAI
    import base64

    client = AsyncOpenAI(api_key=LLM_API_KEY)
    content: list = [{"type": "text", "text": prompt}]

    if image_path:
        with open(image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_data}"}
        })

    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": content}],
        max_tokens=4096,
    )
    return response.choices[0].message.content or ""
