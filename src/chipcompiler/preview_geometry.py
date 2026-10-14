"""Pixel-independent viewport layout for physical geometry previews.

The SVG and Qt scene renderers must never stretch chip geometry to fit a
non-square dock window. This helper is intentionally independent of Qt so it
can be regression tested on build machines without the desktop GUI installed.
"""
from __future__ import annotations
import math


def aspect_fit_rectangle(source_width: float, source_height: float,
                         available_width: float, available_height: float):
    """(left, top, width, height) of centered, uniformly scaled content."""
    values=(source_width,source_height,available_width,available_height)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or
           not math.isfinite(v) or v<=0 for v in values):
        raise ValueError('Preview dimensions must be finite and positive')
    scale=min(available_width/source_width,available_height/source_height)
    width=source_width*scale
    height=source_height*scale
    return ((available_width-width)*0.5,(available_height-height)*0.5,width,height)
