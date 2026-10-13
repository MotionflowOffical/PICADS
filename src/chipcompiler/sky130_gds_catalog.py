"""Verified SKY130 GDS layer/datatype catalogue for KLayout DISPLAY ONLY.

Reference: google/skywater-pdk docs/rules/gds_layers.csv (Apache-2.0 project).
Only pairs explicitly enumerated in the PDK source are named. Unknown pairs
remain numeric rather than receiving invented names. No change to mask data.
"""
from __future__ import annotations

# Official (layer/datatype, purpose) pairs from the SkyWater PDK CSV.
# Common active/device/metal, labels, pins, special purposes and boundaries.
_DATA = '''
64/5 nwell.label
64/16 nwell.pin
64/20 nwell.drawing
64/59 pwell.label
65/4 diff.boundary
65/5 tap.label
65/6 diff.label
65/8 diff.high_voltage
65/13 diff.resistor
65/14 diff.cut
65/16 diff.pin
65/20 diff.drawing
65/23 diff.net
65/44 tap.drawing
65/60 tap.boundary
66/4 poly.boundary
66/5 poly.label
66/9 poly.gate
66/13 poly.resistor
66/14 poly.cut
66/15 poly.short
66/16 poly.pin
66/20 poly.drawing
66/23 poly.net
66/44 licon1.drawing
66/83 poly.model
67/0 li1.pin
67/5 li1.label
67/10 li1.block
67/13 li1.resistor
67/14 li1.cut
67/15 li1.short
67/16 li1.pin
67/20 li1.drawing
67/23 li1.net
67/25 li1.probe
67/44 mcon.drawing
67/60 mcon.boundary
68/0 met1.pin
68/5 met1.label
68/10 met1.block
68/14 met1.cut
68/15 met1.short
68/16 met1.pin
68/20 met1.drawing
68/23 met1.net
68/25 met1.probe
68/44 via.drawing
68/60 via.boundary
69/0 met2.pin
69/5 met2.label
69/10 met2.block
69/14 met2.cut
69/15 met2.short
69/16 met2.pin
69/20 met2.drawing
69/23 met2.net
69/25 met2.probe
69/44 via2.drawing
69/60 via2.boundary
70/0 met3.pin
70/5 met3.label
70/10 met3.block
70/14 met3.cut
70/15 met3.short
70/16 met3.pin
70/20 met3.drawing
70/23 met3.net
70/25 met3.probe
70/44 via3.drawing
70/60 via3.boundary
71/0 met4.pin
71/5 met4.label
71/10 met4.block
71/14 met4.cut
71/15 met4.short
71/16 met4.pin
71/17 met4.fuse
71/20 met4.drawing
71/23 met4.net
71/25 met4.probe
71/44 via4.drawing
71/60 via4.boundary
72/0 met5.pin
72/5 met5.label
72/10 met5.block
72/14 met5.cut
72/15 met5.short
72/16 met5.pin
72/20 met5.drawing
72/23 met5.net
72/25 met5.probe
76/5 pad.label
76/16 pad.pin
76/20 pad.drawing
81/4 areaid.standard_cell
83/44 text.label
93/44 nsdm.drawing
94/20 psdm.drawing
95/20 npc.drawing
235/4 prBndry.boundary
'''

def sky130_known_layers() -> dict[tuple[int,int],str]:
    catalog = {}
    for line in _DATA.strip().splitlines():
        pair, name = line.split()
        layer, datatype = map(int, pair.split('/'))
        catalog[(layer,datatype)] = name
    return catalog
