"""Line icons for the web app: one 24 px grid, 1.75 stroke, current colour.

`icon("pin")` returns inline SVG; icons are decorative (aria-hidden), the
text next to them carries the meaning.
"""

PATHS = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "pin": '<path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21Z"/>'
    '<circle cx="12" cy="9.5" r="2.5"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/>'
    '<path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "passport": '<rect x="5" y="3" width="14" height="18" rx="2"/>'
    '<circle cx="12" cy="10" r="3"/><path d="M9 16.5h6"/>',
    "cap": '<path d="m2.5 9 9.5-4.5L21.5 9 12 13.5 2.5 9Z"/>'
    '<path d="M6.5 11v4.5c1.5 1.3 3.4 2 5.5 2s4-.7 5.5-2V11M21.5 9v5"/>',
    "source": '<path d="M4 6h16M4 12h16M4 18h10"/>',
    "target": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/>'
    '<circle cx="12" cy="12" r=".8" fill="currentColor"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1'
    'V7a1 1 0 0 1 1-1h5"/>',
    "thumb": '<path d="M7 10v10H4V10h3Zm0 0 4-7c1.6 0 2.7 1.2 2.3 2.8L12.6 9h5.2'
    'c1.2 0 2.1 1.1 1.8 2.3l-1.6 7c-.2.9-1 1.7-2 1.7H7"/>',
    "briefcase": '<rect x="3" y="7" width="18" height="13" rx="2"/>'
    '<path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M3 12.5h18"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/>'
    '<circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
    "compass": '<circle cx="12" cy="12" r="8.5"/>'
    '<path d="m15.5 8.5-2 5-5 2 2-5 5-2Z"/>',
    "chart": '<path d="M4 20V4M4 20h16"/><path d="M8 16v-4M12 16V8M16 16v-6"/>',
    "more": '<circle cx="5.5" cy="12" r="1.2" fill="currentColor"/>'
    '<circle cx="12" cy="12" r="1.2" fill="currentColor"/>'
    '<circle cx="18.5" cy="12" r="1.2" fill="currentColor"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10'
    'a2 2 0 0 0 2-2V8l-5-5Z"/>'
    '<path d="M14 3v5h5M9 13h6M9 17h4"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/>',
    "bell": '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15L6 16Z"/>'
    '<path d="M10 20.5a2 2 0 0 0 4 0"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "send": '<path d="M20.5 3.5 3.5 10.5l6.5 3 3 6.5 7.5-16.5Z"/>'
    '<path d="m10 13.5 4-4"/>',
    "download": '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14"/>',
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4v4h-4"/>',
    "building": '<rect x="5" y="3" width="14" height="18" rx="1.5"/>'
    '<path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2M10.5 21v-3h3v3"/>',
    "sliders": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/>'
    '<circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    "globe": '<circle cx="12" cy="12" r="8.5"/>'
    '<path d="M3.5 12h17M12 3.5c2.3 2.4 3.5 5.2 3.5 8.5s-1.2 6.1-3.5 8.5'
    'c-2.3-2.4-3.5-5.2-3.5-8.5S9.7 5.9 12 3.5Z"/>',
    "spark": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18'
    'M6 18l2.5-2.5M15.5 8.5 18 6"/>',
    "chevron": '<path d="m9 6 6 6-6 6"/>',
    "arrow-left": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
}


def icon(name: str, size: int = 18, cls: str = "") -> str:
    css = f' class="ico {cls}"' if cls else ' class="ico"'
    return (
        f'<svg{css} width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{PATHS[name]}</svg>'
    )
