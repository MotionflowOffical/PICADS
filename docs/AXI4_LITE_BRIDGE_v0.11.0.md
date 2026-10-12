# PICADS v0.11 — AXI4-Lite memory adapter

## Implemented, bounded contract

`chipcompiler.axi_lite.axi_lite_master(AXILiteConfig(width=4, address_width=4))` creates a gate-level **AXI4-Lite master** with a PICADS memory-service port. `axi_tagged_fabric(TaggedFabricConfig(memory_backend='external'))` connects the same controller to a tagged concurrent resource fabric and exports AXI channels on the top-level DLS and generated Verilog.

The project mode is `schedule.mode: axi_lite_fabric`. It requires `fabric.memory_backend: external` and supports the existing tagged fabric's 2..8 client / at most eight total outstanding tagged slot constraints. AXI itself can have only **one bus transaction in flight**. Other tagged client requests are queued in fabric slots and arbitrated onto that single memory interface. The arithmetic service domain can remain active independently.

| AXI channel | Master outputs | Slave inputs |
| --- | --- | --- |
| Write address (AW) | `axi_awvalid`, `axi_awaddr` (32) | `axi_awready` |
| Write data (W) | `axi_wvalid`, `axi_wdata` (32), `axi_wstrb` (4) | `axi_wready` |
| Write response (B) | `axi_bready` | `axi_bvalid`, `axi_bresp` (2) |
| Read address (AR) | `axi_arvalid`, `axi_araddr` (32) | `axi_arready` |
| Read data (R) | `axi_rready` | `axi_rvalid`, `axi_rdata` (32), `axi_rresp` (2) |

## Addressing and width mapping

PICADS passes a word index into the external memory channel. AXI4-Lite uses **byte addresses**: PICADS address `n` is exported as AXI address `4*n`. Addresses are 32-bit, low 2 bits zero. The PICADS word width is 1–16 bits; writes drive the lowest `ceil(width/8)` byte strobes. Read data is truncated to the declared logical word width. Endianness and subword write assumptions MUST match the actual AXI slave.

## Handshake behavior

- The adapter captures a request only on `memory_request_valid && memory_request_ready`.
- AW and W handshakes are independent; each VALID and its payload remain stable until individually accepted.
- For writes, it waits for both AW and W to be accepted before accepting a B response. For reads, it accepts R only after AR has been accepted.
- AXI `RESP != OKAY` maps to PICADS `response_fault=1` (distinction between SLVERR and DECERR is retained in the `axi_last_resp` debug output but collapsed to a single downstream fault bit).
- The completed PICADS response is stored until `memory_response_ready` accepts it. Backpressure and reset are respected.
- The bridge uses one synchronous clock/reset domain. It **does not implement clock-domain crossing**.

## Build example

```shell
python -m picads compile examples/axi_lite_fabric
```

The resulting DLS, structural Verilog and `fabric_protocol.json` are placed under the example's `build/latest/` directory. Directed and independent randomized AXI device models check delayed responses, handshakes, writes/readback, fault routing and tag identity. This does not establish formal compliance with every AXI corner case.

## Formal and native checks

`chipcompiler.formal.prepare_axi_lite_formal` generates a bounded SymbiYosys safety harness: AW/W/AR payload stability during backpressure, mutually exclusive read/write channels and reset assumptions. `RUN_FULL_VALIDATION.bat` will execute SymbiYosys/Z3 and an Icarus-generated RTL-vs-DLS comparison only if those tools are actually available. Generating proof collateral is **NOT** a proof.

## Explicitly unsupported

AXI4 full bursts, transaction IDs, reorder buffers, cache coherence, DMA engines, outstanding concurrent AXI bus transactions, unaligned/sub-beat transactions, clock-domain crossing, and PDK-backed bus timing. No DRC/LVS/STA/foundry signoff is implied.
