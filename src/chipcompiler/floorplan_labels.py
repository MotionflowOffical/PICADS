"""Pure layout policy for readable in-block CO macro names.

No Qt dependency: unit tests verify label selection even on headless hosts.
Actual glyph drawing happens in DraggableMacro.paint() at paint time.
"""
from __future__ import annotations
import re


def macro_label_layout(name: str, instance: str, width_px: float, height_px: float) -> dict:
    """Fit a nonempty module identifier in a scene rectangle at current zoom.

    Display complete human-readable names whenever possible, split PascalCase
    onto separate lines; fall back to a compact identifier on tiny items.
    Tooltips retain the full module and instance even at extreme zoom.
    """
    name=str(name or instance or 'Module')
    instance=str(instance or name)
    readable=re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '\n', name).replace('_','_\n')
    readable=readable.strip()
    words=readable.splitlines() or [name]
    if width_px<30 or height_px<16:
        short=re.sub(r'[^A-Za-z0-9]', '', instance).replace('u','',1) or name[0]
        return {'text':short[:4].upper(), 'pixel_font_size':max(5,min(11,int(min(width_px/3,height_px*.70))))}
    if width_px<70 or height_px<45:
        words=[word[:max(2,int(width_px/9))] for word in words]
        label='\n'.join(words[:2])
    else:
        label='\n'.join(words)
        if height_px>=78:
            label+='\n'+instance
    max_line=max(map(len,label.splitlines()))
    count=len(label.splitlines())
    font=min(14.0,(width_px-8)/max(1,max_line*0.63),(height_px-6)/max(1,count*1.28))
    if font<7:
        label=instance if len(instance)<len(name) else name
        max_line=len(label)
        font=min(13.0,(width_px-7)/max(1,max_line*0.63),(height_px-6)/1.35)
    return {'text':label, 'pixel_font_size':max(5,round(font,2))}
