# CO selective enforcement demonstration

This small actual PICADS project uses a 4-bit sequential register to avoid
confusing a giant CPU with the floorplanning demonstration.

The CO module rectangles for `DataRegister` and `ControlInterface` are
**guides**. They do not constitute mapped-cell module fences. Their associated
source program is deliberately tiny.

The 10 µm central `ReservedChannel` is **not a guide**. PICADS translates
its `enforcement: required` hard keepout into LibreLane `FP_OBSTRUCTIONS`.
That asks the floorplanner to create no standard-cell placement sites there.
Upper-layer signal wires and power straps may still cross the rectangle.

To test without WSL, run `picads compile examples/co_selective_enforcement`.
For physical output run the normal PICADS **Generate Physical Layout** action
using a working Ubuntu/SKY130 installation. Inspect `build/latest/config.json`
for `FP_OBSTRUCTIONS`; inspect the flow log and DEF before claiming successful
placement. Manufacturing signoff is separately required.

Try changing `DataRegister.enforcement` to `required`: PICADS will explicitly
refuse to build, because real mapped-cell standard-cell fences for source
modules are not available in this release. It will NOT ignore that request.
