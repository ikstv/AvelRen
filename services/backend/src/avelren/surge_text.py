"""Узгоджені українські фрази для тексту та голосу."""


def surge_body(kind: str, checkpoint_id: int, title: str) -> str:
    starts = {
        "surge_forecast": "Можливий початок масової реєстрації",
        "surge_started": "Почалось зростання черги",
    }
    if kind not in starts:
        raise ValueError("unknown surge kind")
    locations = {17: "на Чопі", 6: "на Краківці", 1: "на Ягодині", 29: "на Ягодині"}
    place = locations.get(checkpoint_id, f"на КПП «{title}»")
    return f"{starts[kind]} {place}"
