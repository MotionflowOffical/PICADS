# PICADS licensing, paid integration, creator credit and contributors

**License:** [PICADS License](../LICENSE)  
**Original and principal creator:** MotionflowOffical  
**Official PICADS source code:** https://github.com/MotionflowOffical/PICADS

## What you may do

PICADS may be run privately in commercial or noncommercial settings to
synthesize, simulate, lay out or design chips and to sell independently
created chips, GDS data, designs or reports, respecting independent IP
rights. You may keep modifications to PICADS private if you run them only
internally and provide independent results, not software access.

You may distribute PICADS or modified PICADS for free with exact modifiable
Corresponding Source and the required notices. You **cannot** sell standalone
PICADS copies, ordinary forks, or paid access to a substantially identical
PICADS hosted service without actual rightsholder authorization.

## Paid bundles and integrated hosted platforms

A company **can include PICADS in a paid program, product or service** with
material independent functionality. The host application's independently
written code is not automatically required to be made public. All of these
conditions must be met under LICENSE Section 3:

1. The host genuinely does independent work; a launcher, cosmetic fork or
   insignificant add-on is not an eligible paid integration.
2. Publish the **exact PICADS component source as shipped or deployed**,
   including all PICADS modifications, build scripts and affected adapters,
   without purchase, fee, account or other access gate.
3. Provide a stable public HTTPS download; maintain access throughout
   distribution/support **and at least 3 years afterward**. Make the PICADS
   component independently buildable without a proprietary paid host key.
4. Name PICADS explicitly within the product, credit the principal creator,
   link both the [official PICADS repository](https://github.com/MotionflowOffical/PICADS) and the
   **modified PICADS component's free exact-version source location**.
5. Preserve the PICADS license on the PICADS component; do not impose a
   conflicting EULA, DRM, access requirement or sublicense. Don't imply that
   the original creator endorses the integrated product.

### Examples

| Scenario | Result |
|---|---|
| Commercial design work using a privately modified internal PICADS tool | Allowed; credit required, no private source publication |
| Selling chips or layout files created by PICADS | Allowed; credit the original creator in relevant deliverable documentation |
| Free distribution of a PICADS fork with full matching source | Allowed under the license |
| Paid EDA application with substantive independent functions and public free exact modified PICADS source | Allowed paid integration |
| Paid hosted multipurpose design platform with PICADS backend and public free exact modified PICADS source | Allowed paid integration |
| Selling stock PICADS binary or a minimally rebranded fork | Not allowed without explicit permission |
| Paywalling the ordinary PICADS web interface and pointing at an old upstream source | Not allowed; a link to the upstream source is insufficient |

## Mandatory attribution, including internal commercial work

Use this notice with public or confidential client outputs and relevant
product documentation (not necessarily on a physical chip):

> Made using **PICADS — Procedural Integrated Circuit Architecture and Design
> System**. Original and principal creator: **MotionflowOffical**.
> Official PICADS source code: [https://github.com/MotionflowOffical/PICADS](https://github.com/MotionflowOffical/PICADS)

For work used entirely within a business, **one record per project, product
family or toolchain suffices**. It may be an internal README, engineering wiki,
manifest or compliance register containing the complete notice, an identifier
of the PICADS-using project/toolchain, and the version/commit where known.
Keep it throughout use and at least three years afterward; contractors and
subsidiaries may share a discoverable centralized record. No notice on every
run is required and no general inspection rights are given. Customer secrets
need not be disclosed merely to demonstrate the attribution notice.

**Two different URLs can be mandatory** for paid integrations: the original
PICADS URL above identifies the creator; a distinct freely accessible URL
identifies the exact modified PICADS source used in that paid bundle. Neither
one may stand in for the other.

## Contributor copyright and licensing authority

The source license grants only rights the relevant original author actually
controls. Contributions accepted into the official project require a signed [CLA](CONTRIBUTOR_AGREEMENT.md). Contributors
retain their copyright but authorize the receiving PICADS rightsholder to
license accepted changes under alternate future terms. This does not reach
unaffiliated forks or retroactively cover existing contributors.

## Previously free public editions and separate author editions

PICADS editions actually made publicly available for free retain the
permissions already granted for those copies. A later paid edition cannot
make previously free public code payment-only or take away the rights of
recipients who lawfully received it. The original author can separately
offer an author-controlled edition that was NOT previously made publicly
available for free under different terms, to the extent the author owns
or has permission for all code included. A rename, fork or repackaging
does not create the original author's exclusive distribution rights.

## WIP, scope and older copies

Read [known issues and unverified functions](KNOWN_ISSUES_AND_LIMITATIONS.md)
before relying on PICADS output. GDS generation does not prove tapeout
readiness. Other PDKs, EDA tools and third-party libraries have separate
licenses. Copies previously made publicly available for free remain subject to their
existing permissions, even if the author publishes separate paid editions.
Publish the exact PICADS source when free distribution or the paid-integration
exception requires it. Verify actual ownership and signed CLA permissions;
credit does not transfer rights.
